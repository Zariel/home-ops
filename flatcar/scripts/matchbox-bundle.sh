#!/usr/bin/env bash

set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

need awk
need curl
need git
need openssl

ROOT=$(git rev-parse --show-toplevel)
MATCHBOX_DIR="$ROOT/artifacts/flatcar/matchbox"
ASSETS_DIR="$MATCHBOX_DIR/assets/flatcar"

FLATCAR_CHANNEL=${FLATCAR_CHANNEL:-stable}
FLATCAR_ARCH=${FLATCAR_ARCH:-amd64-usr}
FLATCAR_VERSION=${FLATCAR_VERSION:-current}
FLATCAR_BASE_URL=${FLATCAR_BASE_URL:-https://${FLATCAR_CHANNEL}.release.flatcar-linux.net/${FLATCAR_ARCH}}
FLATCAR_BASE_URL=${FLATCAR_BASE_URL%/}
FLATCAR_RELEASE_URL="${FLATCAR_BASE_URL}/${FLATCAR_VERSION}"
FLATCAR_INSTALLERS=${FLATCAR_INSTALLERS:-all}

ASSET_FILES=(
  flatcar_production_pxe.vmlinuz
  flatcar_production_pxe_image.cpio.gz
)

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

echo "Rendering Flatcar matchbox artifacts..."
"$ROOT/flatcar/render.sh"

mkdir -p "$ASSETS_DIR"

select_installer_groups() {
  local group host keep selected
  local selected_hosts

  case "$FLATCAR_INSTALLERS" in
    all)
      echo "Keeping installer groups for all nodes"
      return
      ;;
    none | "")
      echo "Removing all installer groups"
      rm -f "$MATCHBOX_DIR"/groups/*-installer.json
      return
      ;;
  esac

  IFS=',' read -r -a selected_hosts <<< "$FLATCAR_INSTALLERS"
  for selected in "${selected_hosts[@]}"; do
    selected=${selected//[[:space:]]/}
    if [[ -n "$selected" && ! -f "$MATCHBOX_DIR/groups/${selected}-installer.json" ]]; then
      echo "unknown installer node: ${selected}" >&2
      exit 1
    fi
  done

  for group in "$MATCHBOX_DIR"/groups/*-installer.json; do
    [[ -e "$group" ]] || continue
    host=$(basename "$group" -installer.json)
    keep=false
    for selected in "${selected_hosts[@]}"; do
      selected=${selected//[[:space:]]/}
      if [[ "$selected" == "$host" ]]; then
        keep=true
        break
      fi
    done
    if [[ "$keep" != true ]]; then
      rm -f "$group"
    fi
  done
}

download() {
  local url=$1
  local dest=$2
  local tmp=$3

  curl -fsSL --retry 3 --retry-delay 1 --retry-connrefused -o "$tmp" "$url"
  mv "$tmp" "$dest"
}

expected_sha512() {
  local digest_file=$1
  local asset=$2

  awk -v asset="$asset" '
    /^# SHA512 HASH/ { sha512 = 1; next }
    /^#/ { next }
    sha512 && $2 == asset { print $1; exit }
  ' "$digest_file"
}

actual_sha512() {
  local asset_file=$1

  openssl dgst -sha512 -r "$asset_file" | awk '{ print $1 }'
}

select_installer_groups

echo "Resolving Flatcar ${FLATCAR_CHANNEL}/${FLATCAR_ARCH}/${FLATCAR_VERSION}..."
download "$FLATCAR_RELEASE_URL/version.txt" "$tmpdir/version.txt" "$tmpdir/version.txt.tmp"
resolved_version=$(awk -F= '/^FLATCAR_VERSION=/{ gsub(/"/, "", $2); print $2; exit }' "$tmpdir/version.txt")
if [[ -z "$resolved_version" ]]; then
  echo "failed to resolve Flatcar version from ${FLATCAR_RELEASE_URL}/version.txt" >&2
  exit 1
fi

version_dir="$ASSETS_DIR/$resolved_version"
mkdir -p "$version_dir"
cp "$tmpdir/version.txt" "$version_dir/version.txt"

for asset in "${ASSET_FILES[@]}"; do
  digest_file="$tmpdir/${asset}.DIGESTS"
  asset_file="$version_dir/$asset"

  echo "Downloading ${asset}..."
  download "$FLATCAR_RELEASE_URL/${asset}.DIGESTS" "$digest_file" "$digest_file.tmp"
  download "$FLATCAR_RELEASE_URL/${asset}" "$asset_file" "$asset_file.tmp"

  expected=$(expected_sha512 "$digest_file" "$asset")
  if [[ -z "$expected" ]]; then
    echo "missing SHA512 digest for ${asset}" >&2
    exit 1
  fi

  actual=$(actual_sha512 "$asset_file")
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA512 mismatch for ${asset}" >&2
    echo "expected: $expected" >&2
    echo "actual:   $actual" >&2
    exit 1
  fi

  cp "$digest_file" "$version_dir/${asset}.DIGESTS"
done

ln -sfn "$resolved_version" "$ASSETS_DIR/current"

echo "Bundle ready at ${MATCHBOX_DIR}"
