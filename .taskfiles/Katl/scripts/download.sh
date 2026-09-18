#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
version=$(cat "$root/katl/version")
out="$root/artifacts/katl/$version"
mkdir -p "$out"
assets=("katlctl-$version-linux-amd64" katl-installer.vmlinuz katl-installer.initrd
  "katlos-install-$version-x86_64.squashfs" "katlos-install-$version-x86_64.squashfs.json")
args=(--repo katl-dev/katl --dir "$out" --skip-existing --pattern SHA256SUMS)
for asset in "${assets[@]}"; do args+=(--pattern "$asset"); done
gh release download "v$version" "${args[@]}"
cd "$out"
for asset in "${assets[@]}"; do
  awk -v file="$asset" '$2 == file {print; found=1} END {if (!found) exit 1}' SHA256SUMS | sha256sum --check -
done
chmod +x "katlctl-$version-linux-amd64"
