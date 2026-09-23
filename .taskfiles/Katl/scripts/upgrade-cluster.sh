#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
katlctl="$root/.taskfiles/Katl/scripts/katlctl"
config="$root/katl/cluster.yaml"
version=${1:-}

if [[ ! $version =~ ^[0-9]{4}\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
  echo 'Pass a Katl release version, for example: task katl:cluster:upgrade version=2026.9.0-beta.14' >&2
  exit 1
fi

for command in kubectl kubectl-cnpg jq yq; do
  command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 1; }
done

mapfile -t nodes < <(yq -r '.nodes[].hostname' "$root/katl/nodes.yaml")
if ((${#nodes[@]} == 0)); then
  echo 'No nodes found in katl/nodes.yaml' >&2
  exit 1
fi

healthy() {
  local ceph cnpg backups namespace name primary streaming expected status

  ceph=$(kubectl get cephclusters.ceph.rook.io -A -o json) || return 1
  jq -e '(.items | length) > 0 and all(.items[]; .status.phase == "Ready" and .status.ceph.health == "HEALTH_OK")' <<<"$ceph" >/dev/null || return 1

  # The CephCluster status can lag behind Ceph itself after an OSD restarts.
  while IFS=$'\t' read -r namespace name; do
    status=$(kubectl -n "$namespace" exec deploy/rook-ceph-tools -- ceph status --format json) || return 1
    jq -e '.health.status == "HEALTH_OK" and .osdmap.num_osds > 0 and .osdmap.num_up_osds == .osdmap.num_osds and .osdmap.num_in_osds == .osdmap.num_osds and .pgmap.num_pgs > 0 and (all(.pgmap.pgs_by_state[]; .state_name == "active+clean"))' <<<"$status" >/dev/null || return 1
  done < <(jq -r '.items[] | [.metadata.namespace, .metadata.name] | @tsv' <<<"$ceph")

  cnpg=$(kubectl get clusters.postgresql.cnpg.io -A -o json) || return 1
  jq -e '(.items | length) > 0 and all(.items[];
    .status.phase == "Cluster in healthy state" and
    .status.readyInstances == .spec.instances and
    (.status.instancesStatus.healthy | length) == .spec.instances and
    .status.currentPrimary == .status.targetPrimary and
    any(.status.conditions[]; .type == "Ready" and .status == "True") and
    (if any(.spec.plugins[]?; .isWALArchiver == true) then
      any(.status.conditions[]; .type == "ContinuousArchiving" and .status == "True") and
      any(.status.conditions[]; .type == "LastBackupSucceeded" and .status == "True")
    else true end))' <<<"$cnpg" >/dev/null || return 1

  backups=$(kubectl get backups.postgresql.cnpg.io -A -o json) || return 1
  jq -e --argjson clusters "$cnpg" '.items as $backups | all(
    $clusters.items[] | select(any(.spec.plugins[]?; .isWALArchiver == true));
    . as $cluster | any($backups[];
      .metadata.namespace == $cluster.metadata.namespace and
      .spec.cluster.name == $cluster.metadata.name and
      .status.phase == "completed" and
      (.status.stoppedAt | fromdateiso8601) >= now - 172800))' <<<"$backups" >/dev/null || return 1

  while IFS=$'\t' read -r namespace name primary; do
    # CNPG readiness alone does not establish that its replicas are streaming.
    streaming=$(kubectl -n "$namespace" exec "$primary" -c postgres -- \
      psql -X -U postgres -d postgres -Atqc \
      "SELECT coalesce(string_agg(application_name, ',' ORDER BY application_name), '') FROM pg_stat_replication WHERE state = 'streaming' AND replay_lsn IS NOT NULL AND pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) <= 16777216") || return 1
    expected=$(jq -r --arg name "$name" --arg namespace "$namespace" \
      '.items[] | select(.metadata.name == $name and .metadata.namespace == $namespace) | .status.currentPrimary as $primary | [.status.instancesStatus.healthy[] | select(. != $primary)] | sort | join(",")' <<<"$cnpg")
    [[ $streaming == "$expected" ]] || return 1
  done < <(jq -r '.items[] | [.metadata.namespace, .metadata.name, .status.currentPrimary] | @tsv' <<<"$cnpg")
}

wait_healthy() {
  local deadline=$((SECONDS + 1800)) attempts=0
  echo 'Waiting for all Ceph and CNPG clusters to recover...'
  until healthy; do
    if ((SECONDS >= deadline)); then
      echo 'Timed out waiting for Ceph and CNPG health; stopping before the next node.' >&2
      kubectl get cephclusters.ceph.rook.io -A >&2 || true
      kubectl get clusters.postgresql.cnpg.io -A >&2 || true
      return 1
    fi
    ((attempts += 1))
    if ((attempts % 4 == 0)); then
      echo 'Still waiting for Ceph and CNPG health...'
    fi
    sleep 15
  done
}

wait_primary() {
  local namespace=$1 name=$2 candidate=$3 deadline=$((SECONDS + 600)) current
  until [[ ${current:-} == "$candidate" ]]; do
    if ((SECONDS >= deadline)); then
      echo "Timed out waiting for $namespace/$name to promote $candidate" >&2
      return 1
    fi
    sleep 5
    current=$(kubectl -n "$namespace" get cluster "$name" -o jsonpath='{.status.currentPrimary}') || return 1
  done
}

switch_primary() {
  local node=$1 clusters namespace name primary candidate pods
  clusters=$(kubectl get clusters.postgresql.cnpg.io -A -o json)
  while IFS=$'\t' read -r namespace name primary; do
    pods=$(kubectl -n "$namespace" get pods -l "cnpg.io/cluster=$name" -o json)
    if ! jq -e --arg primary "$primary" \
      'any(.items[]; .metadata.name == $primary)' <<<"$pods" >/dev/null; then
      echo "Primary pod $primary is missing from $namespace/$name" >&2
      return 1
    fi
    if ! jq -e --arg primary "$primary" --arg node "$node" \
      'any(.items[]; .metadata.name == $primary and .spec.nodeName == $node)' <<<"$pods" >/dev/null; then
      continue
    fi

    candidate=$(jq -r --arg node "$node" \
      '[.items[] | select(.spec.nodeName != $node and .metadata.labels["cnpg.io/instanceRole"] == "replica") | .metadata.name][0] // empty' <<<"$pods")
    if [[ -z $candidate ]]; then
      echo "No replica available outside $node for $namespace/$name" >&2
      return 1
    fi

    echo "Switching $namespace/$name primary from $primary to $candidate"
    kubectl cnpg promote "$name" "$candidate" -n "$namespace"
    wait_primary "$namespace" "$name" "$candidate"
    wait_healthy
  done < <(jq -r '.items[] | [.metadata.namespace, .metadata.name, .status.currentPrimary] | @tsv' <<<"$clusters")
}

# Validate every upgrade while all nodes and workloads are still available.
for node in "${nodes[@]}"; do
  kubectl wait "node/$node" --for=condition=Ready --timeout=30s
  if ! kubectl get "node/$node" -o json | jq -e '.spec.unschedulable != true' >/dev/null; then
    echo "$node is cordoned; inspect and recover it before upgrading the cluster." >&2
    exit 1
  fi
  "$katlctl" node upgrade "$node" --version "$version" --config "$config" --plan
done
wait_healthy

for node in "${nodes[@]}"; do
  echo "Upgrading $node to $version"
  wait_healthy
  switch_primary "$node"
  kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --force --timeout=20m
  # Leave a failed node cordoned so the next node cannot be touched accidentally.
  "$katlctl" node upgrade "$node" --version "$version" --config "$config"
  kubectl uncordon "$node"
  kubectl wait "node/$node" --for=condition=Ready --timeout=15m
  wait_healthy
done
