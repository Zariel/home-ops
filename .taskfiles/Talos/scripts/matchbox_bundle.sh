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

ROOT=$(git rev-parse --show-toplevel)
OUT_DIR="$ROOT/artifacts/matchbox"
CACHE_DIR="$ROOT/talos/.cache"
NODES_FILE="$ROOT/talos/nodes.yaml"
TALCONFIG="$ROOT/talos/talconfig.yaml"

PROFILE_PREFIX=${MATCHBOX_PROFILE_PREFIX:-talos}
CONFIG_URL_BASE=${MATCHBOX_CONFIG_URL_BASE:-http://10.5.0.8/assets}

mkdir -p "$OUT_DIR"/{assets,profiles,groups} "$CACHE_DIR"

cluster_name=$(yq -r '.clusterName' "$TALCONFIG")
talos_version=$(yq -r '.talosVersion' "$TALCONFIG")

# Customization block is what defines the schematic; hash it + version to cache the ID.
customization_json=$(yq -o=json '.controlPlane.schematic.customization' "$TALCONFIG")
input_hash=$(printf "%s\n%s" "$talos_version" "$customization_json" | sha256sum | cut -d' ' -f1)

cache_key_file="$CACHE_DIR/schematic.key"
cache_id_file="$CACHE_DIR/schematic.id"

resolve_schematic_id() {
  if [[ -f "$cache_key_file" && -f "$cache_id_file" ]] && [[ "$(cat "$cache_key_file")" == "$input_hash" ]]; then
    cat "$cache_id_file"
    return
  fi

  echo "Fetching schematic id from Talos Factory..." >&2
  schematic_id=$(curl -fsSL -X POST \
    -H "Content-Type: application/json" \
    -d "{\"customization\":$customization_json}" \
    https://factory.talos.dev/schematics | jq -r '.id')

  if [[ -z "$schematic_id" || "$schematic_id" == "null" ]]; then
    echo "failed to obtain schematic id" >&2
    exit 1
  fi

  printf "%s" "$input_hash" > "$cache_key_file"
  printf "%s" "$schematic_id" > "$cache_id_file"
  echo "$schematic_id"
}

SCHEMATIC_ID=$(resolve_schematic_id)
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

# Copy Talos machine configs produced by talhelper.
for row in $(yq -o=json '.nodes[]' "$NODES_FILE" | jq -c '.'); do
  host=$(jq -r '.hostname' <<<"$row")
  src="$ROOT/talos/clusterconfig/${cluster_name}-${host}.yaml"
  dest="$OUT_DIR/assets/${host}.yaml"
  if [[ ! -f "$src" ]]; then
    echo "machine config missing for ${host}: run talhelper genconfig" >&2
    exit 1
  fi
  cp "$src" "$dest"
done

# Render per-node profiles and groups.
while IFS= read -r node; do
  host=$(jq -r '.hostname' <<<"$node")
  mac=$(jq -r '.mac' <<<"$node")
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
done <<<"$(yq -o=json '.nodes[]' "$NODES_FILE" | jq -c '.')"

echo "Bundle ready at ${OUT_DIR}"
