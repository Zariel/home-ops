#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
export TEST_DIR="$test_dir"
export PATH="$test_dir/bin:$PATH"
mkdir "$test_dir/bin"

cat >"$test_dir/bin/yq" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' k8s-0 k8s-1 k8s-2
EOF

cat >"$test_dir/bin/katlctl" <<'EOF'
#!/usr/bin/env bash
if [[ ${*: -1} == --plan ]]; then
  echo "plan $3" >>"$TEST_DIR/actions"
else
  echo "upgrade $3" >>"$TEST_DIR/actions"
  echo 2026.10.1 >"$TEST_DIR/version"
fi
EOF

cat >"$test_dir/bin/kubectl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  'get node/'*)
    if [[ $2 == node/k8s-1 ]]; then
      [[ ! -e $TEST_DIR/fail ]] || exit 1
      version=$(cat "$TEST_DIR/version")
    else
      version=2026.10.1
    fi
    printf '{"spec":{},"status":{"nodeInfo":{"osImage":"KatlOS %s"}}}\n' "$version"
    ;;
  'get cephclusters.ceph.rook.io -A -o json')
    echo '{"items":[{"metadata":{"namespace":"rook-ceph","name":"ceph"},"status":{"phase":"Ready","ceph":{"health":"HEALTH_OK"}}}]}'
    ;;
  '-n rook-ceph exec deploy/rook-ceph-tools -- ceph status --format json')
    echo '{"health":{"status":"HEALTH_OK"},"osdmap":{"num_osds":3,"num_up_osds":3,"num_in_osds":3},"pgmap":{"num_pgs":1,"pgs_by_state":[{"state_name":"active+clean"}]}}'
    ;;
  'get clusters.postgresql.cnpg.io -A -o json')
    echo '{"items":[{"metadata":{"namespace":"db","name":"db"},"spec":{"instances":1},"status":{"phase":"Cluster in healthy state","readyInstances":1,"instancesStatus":{"healthy":["db-1"]},"currentPrimary":"db-1","targetPrimary":"db-1","conditions":[{"type":"Ready","status":"True"}]}}]}'
    ;;
  'get backups.postgresql.cnpg.io -A -o json') echo '{"items":[]}' ;;
  '-n db exec db-1 -c postgres -- psql '*) echo '' ;;
  '-n db get pods -l cnpg.io/cluster=db -o json')
    echo '{"items":[{"metadata":{"name":"db-1"},"spec":{"nodeName":"database-worker"}}]}'
    ;;
  'wait '*) ;;
  'drain '*|'uncordon '*|'cnpg '*) echo "kubectl $*" >>"$TEST_DIR/actions" ;;
  *) echo "Unexpected kubectl call: $*" >&2; exit 1 ;;
esac
EOF

cat >"$test_dir/bin/kubectl-cnpg" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$test_dir/bin/"*

# Matching nodes must cause no upgrade plans, switchovers, drains, or upgrades.
echo 2026.10.1 >"$test_dir/version"
: >"$test_dir/actions"
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1
diff -u /dev/null "$test_dir/actions"

# A different release sharing the target prefix must still upgrade exactly once.
echo 2026.10.10 >"$test_dir/version"
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1
cat >"$test_dir/expected" <<'EOF'
plan k8s-1
kubectl drain k8s-1 --ignore-daemonsets --delete-emptydir-data --force --timeout=20m
upgrade k8s-1
kubectl uncordon k8s-1
EOF
diff -u "$test_dir/expected" "$test_dir/actions"
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1
diff -u "$test_dir/expected" "$test_dir/actions"

# An unreadable node must stop the run before any disruptive operation.
: >"$test_dir/actions"
touch "$test_dir/fail"
if bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1; then
  echo 'Expected a failed node query to stop the upgrade' >&2
  exit 1
fi
test ! -s "$test_dir/actions"
