#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="${ROOT}/flatcar/config.pkl"

node=""
host=""
user="core"
entry=""
mac=""
list_only="false"
reboot="false"

usage() {
  cat <<'USAGE'
Usage: flatcar/scripts/pxe-once.sh (--node NAME | --host HOST) [options]

Options:
  --node NAME       Resolve SSH host from flatcar/config.pkl management_ip
  --host HOST       SSH host/IP to connect to directly
  --user USER       SSH user (default: core)
  --entry BOOTNUM   Use explicit UEFI Boot#### value, for example 0007
  --mac MAC         Match PXE entry by MAC address; defaults to node mac with --node
  --reboot          Start the one-time PXE service, which sets BootNext and reboots
  --list            Print remote efibootmgr -v output and exit
  -h, --help        Show this help

Without --reboot, this sets BootNext without rebooting by running the host
helper directly. With --reboot, this starts the matching one-shot systemd unit
on the remote node.
USAGE
}

normalize_mac() {
  local value="${1,,}"
  value="${value//:/}"
  value="${value//-/}"

  if [[ ! "${value}" =~ ^[0-9a-f]{12}$ ]]; then
    echo "MAC address must contain 12 hex digits: $1" >&2
    exit 2
  fi

  printf '%s\n' "${value}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --node)
      node="${2:?missing value for --node}"
      shift 2
      ;;
    --host)
      host="${2:?missing value for --host}"
      shift 2
      ;;
    --user)
      user="${2:?missing value for --user}"
      shift 2
      ;;
    --entry)
      entry="${2:?missing value for --entry}"
      shift 2
      ;;
    --mac)
      mac="${2:?missing value for --mac}"
      shift 2
      ;;
    --reboot)
      reboot="true"
      shift
      ;;
    --list)
      list_only="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "${node}" && -n "${host}" ]]; then
  echo "Use either --node or --host, not both" >&2
  exit 2
fi

if [[ -z "${node}" && -z "${host}" ]]; then
  echo "Either --node or --host is required" >&2
  usage >&2
  exit 2
fi

if [[ -n "${entry}" && ! "${entry}" =~ ^[0-9A-Fa-f]{4}$ ]]; then
  echo "--entry must be a four digit UEFI Boot#### value, for example 0007" >&2
  exit 2
fi

if [[ -n "${node}" ]]; then
  if ! command -v pkl >/dev/null 2>&1; then
    echo "missing required command: pkl" >&2
    exit 1
  fi

  node_config="$(
    python3 - "$CONFIG" "$node" <<'PY'
import ipaddress
import json
import subprocess
import sys

config_path, node_name = sys.argv[1], sys.argv[2]
config = json.loads(subprocess.check_output(["pkl", "eval", "--format", "json", config_path], text=True))

for node in config.get("nodes", []):
    if node.get("hostname") == node_name:
        print(ipaddress.ip_interface(node["management_ip"]).ip)
        print(node.get("mac", ""))
        break
else:
    print(f"Node not found in {config_path}: {node_name}", file=sys.stderr)
    sys.exit(1)
PY
  )"

  host="${node_config%%$'\n'*}"
  if [[ -z "${mac}" ]]; then
    mac="${node_config#*$'\n'}"
    if [[ "${mac}" == "${node_config}" ]]; then
      mac=""
    fi
  fi
fi

if [[ -n "${mac}" ]]; then
  mac="$(normalize_mac "${mac}")"
fi

ssh_target="${user}@${host}"
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)

remote_args=()
if [[ -n "${mac}" ]]; then
  remote_args+=(--mac "${mac}")
fi

if [[ "${list_only}" == "true" ]]; then
  ssh "${ssh_opts[@]}" "${ssh_target}" "sudo /opt/bin/flatcar-pxe-once --list"
  exit 0
fi

if [[ "${reboot}" == "true" ]]; then
  if [[ -n "${entry}" ]]; then
    echo "Starting flatcar-pxe-once@${entry^^}.service on ${ssh_target}..."
    ssh "${ssh_opts[@]}" "${ssh_target}" "sudo systemctl start flatcar-pxe-once@${entry^^}.service"
  elif [[ -n "${mac}" ]]; then
    echo "Starting flatcar-pxe-once-mac@${mac}.service on ${ssh_target}..."
    ssh "${ssh_opts[@]}" "${ssh_target}" "sudo systemctl start flatcar-pxe-once-mac@${mac}.service"
  else
    echo "Starting flatcar-pxe-once.service on ${ssh_target}..."
    ssh "${ssh_opts[@]}" "${ssh_target}" "sudo systemctl start flatcar-pxe-once.service"
  fi
  exit 0
fi

if [[ -n "${entry}" ]]; then
  ssh "${ssh_opts[@]}" "${ssh_target}" "sudo /opt/bin/flatcar-pxe-once --entry ${entry^^}"
else
  ssh "${ssh_opts[@]}" "${ssh_target}" "sudo /opt/bin/flatcar-pxe-once ${remote_args[*]}"
fi
