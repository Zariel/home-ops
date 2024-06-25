#!/usr/bin/env bash

set -euo pipefail

NODE="${1}"
TALOS_STANZA="${2}"
ROLLOUT="${3:-false}"

FROM_VERSION=$(kubectl get node "${NODE}" --output jsonpath='{.metadata.labels.feature\.node\.kubernetes\.io/system-os_release\.VERSION_ID}')
TO_VERSION=${TALOS_STANZA##*:}

cmd=$(talhelper gencommand upgrade -c talos/talconfig.yaml)

echo "cmd=${cmd}"

exit 0

echo "Checking if Talos needs to be upgraded on node '${NODE}' in cluster..."
if [ "${FROM_VERSION}" == "${TO_VERSION}" ]; then
    echo "Talos is already up to date on version '${FROM_VERSION}', skipping '${NODE}' upgrade..."
    exit 0
fi

echo "Waiting for all jobs to complete before upgrading Talos..."
until kubectl wait --timeout=5m \
    --for=condition=Complete jobs --all --all-namespaces;
do
    echo "Waiting for jobs to complete..."
    sleep 10
done

if [ "${ROLLOUT}" != "true" ]; then
    echo "Suspending Flux Kustomizations in cluster..."
    flux suspend kustomization --all
    echo "Setting CNPG maintenance mode in cluster..."
    kubectl cnpg maintenance set --reusePVC --all-namespaces
fi

echo "Upgrading Talos on node ${NODE}..."
talosctl --nodes "${NODE}" upgrade \
    --image="factory.talos.dev/installer/${TALOS_STANZA}" \
        --wait=true --timeout=10m --preserve=true

echo "Waiting for Talos to be healthy..."
talosctl --nodes "${NODE}" health \
    --wait-timeout=10m --server=false

echo "Waiting for Ceph health to be OK..."
until kubectl wait --timeout=5m \
    --for=jsonpath=.status.ceph.health=HEALTH_OK cephcluster \
        --all --all-namespaces;
do
    echo "Waiting for Ceph health to be OK..."
    sleep 10
done

if [ "${ROLLOUT}" != "true" ]; then
    echo "Resuming Flux Kustomizations in cluster..."
    flux resume kustomization --all
    echo "Unsetting CNPG maintenance mode in cluster..."
    kubectl cnpg maintenance unset --reusePVC --all-namespaces
fi
