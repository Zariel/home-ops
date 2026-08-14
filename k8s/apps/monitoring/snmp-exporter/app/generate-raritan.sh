#!/usr/bin/env bash
set -euo pipefail

# Regenerate only the Raritan PX2 snmp_exporter module.
# Usage: ./generate-raritan.sh

SCRIPT_DIR="$(cd -- "$(dirname "$0")" && pwd)"
WORK_DIR="${SCRIPT_DIR}"

IMAGE="quay.io/prometheus/snmp-generator:v0.29.0"

# Add --platform=linux/amd64 for Apple Silicon hosts to avoid qemu warnings.
PLATFORM_FLAG=${PLATFORM_FLAG:-"--platform=linux/amd64"}

docker run --rm \
  ${PLATFORM_FLAG} \
  -v "${WORK_DIR}:/work" \
  "${IMAGE}" \
  generate \
  -g /work/generator-raritan.yml \
  -o /work/resources/snmp-raritan.yaml \
  -m /work/mibs \
  -m /work/mibs/standard

echo "snmp-raritan.yaml regenerated at ${WORK_DIR}/resources/snmp-raritan.yaml"
