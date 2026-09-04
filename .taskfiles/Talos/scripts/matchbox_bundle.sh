#!/usr/bin/env bash

set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

need yq
need jq
need curl
need sha256sum
need git
need topf

ROOT=$(git rev-parse --show-toplevel)
OUT_DIR="$ROOT/artifacts/matchbox"
TOPF_CONFIG="$ROOT/talos/topf.yaml"

PROFILE_PREFIX=${MATCHBOX_PROFILE_PREFIX:-talos}
CONFIG_URL_BASE=${MATCHBOX_CONFIG_URL_BASE:-http://10.5.0.8/assets}

mkdir -p "$OUT_DIR"/{assets,profiles,groups}

talos_version=$(yq -r '.talosVersion' "$TOPF_CONFIG")

# Matchbox exposes one stable boot-asset path, so every provisioned node must
# resolve to the same Image Factory schematic.
mapfile -t schematic_ids < <(topf --topfconfig "$TOPF_CONFIG" schematic-ids)
if [[ ${#schematic_ids[@]} -ne 1 ]]; then
  echo "expected exactly one schematic ID, got ${#schematic_ids[@]}" >&2
  exit 1
fi
SCHEMATIC_ID=${schematic_ids[0]}
SCHEMATIC_DIR="$OUT_DIR/assets/$SCHEMATIC_ID"
mkdir -p "$SCHEMATIC_DIR"

download_asset() {
  local file=$1
  local url="https://factory.talos.dev/image/${SCHEMATIC_ID}/${talos_version}/${file}"
  local dest="$SCHEMATIC_DIR/$file"
  tmp="${dest}.tmp"
  echo "Downloading ${file}..."
  curl -fsSL --retry 3 --retry-delay 1 -o "$tmp" "$url"
  mv "$tmp" "$dest"
}

download_asset "kernel-amd64"
download_asset "initramfs-amd64.xz"

echo "Writing sha256sums..."
(
  cd "$SCHEMATIC_DIR"
  sha256sum kernel-amd64 initramfs-amd64.xz > sha256sums.txt
) >/dev/null

# Symlink to stable path for profiles.
ln -sfn "$SCHEMATIC_ID" "$OUT_DIR/assets/current"

# Copy Talos machine configs produced by TOPF.
for row in $(yq -o=json '.nodes[]' "$TOPF_CONFIG" | jq -c '.'); do
  host=$(jq -r '.host' <<<"$row")
  src="$ROOT/talos/clusterconfig/${host}.yaml"
  dest="$OUT_DIR/assets/${host}.yaml"
  if [[ ! -f "$src" ]]; then
    echo "machine config missing for ${host}: run task talos:generate" >&2
    exit 1
  fi
  cp "$src" "$dest"
done

# Render per-node profiles and groups.
while IFS= read -r node; do
  host=$(jq -r '.host' <<<"$node")
  mac=$(jq -r '.data.mac' <<<"$node")
  profile="${PROFILE_PREFIX}-${host}"

  cat > "$OUT_DIR/profiles/${profile}.json" <<EOF
{
  "id": "${profile}",
  "name": "${profile}",
  "boot": {
    "kernel": "/assets/current/kernel-amd64",
    "initrd": ["/assets/current/initramfs-amd64.xz"],
    "args": [
      "initrd=initramfs-amd64.xz",
      "init_on_alloc=1",
      "slab_nomerge",
      "pti=on",
      "console=tty0",
      "console=ttyS0",
      "printk.devkmsg=on",
      "talos.platform=metal",
      "talos.config=${CONFIG_URL_BASE}/${host}.yaml",
      "talos.halt_if_installed=1"
    ]
  }
}
EOF

  cat > "$OUT_DIR/groups/${host}.json" <<EOF
{
  "id": "${host}",
  "name": "${host}",
  "profile": "${profile}",
  "selector": {
    "mac": "${mac}"
  }
}
EOF
done <<<"$(yq -o=json '.nodes[]' "$TOPF_CONFIG" | jq -c '.')"

echo "Bundle ready at ${OUT_DIR}"
