#!/usr/bin/env bash
set -euo pipefail
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
version=$(cat "$root/katl/version")
out="$root/artifacts/matchbox-katl"
relative="katl/$version"
assets="$out/assets/$relative"
base="${MATCHBOX_URL:-http://10.5.0.8}"
base=${base%/}
cli="$root/.taskfiles/Katl/scripts/katlctl"
mkdir -p "$assets" "$out/profiles" "$out/groups"
for file in katl-installer.vmlinuz katl-installer.initrd "katlos-install-$version-x86_64.squashfs" "katlos-install-$version-x86_64.squashfs.json"; do
  cp "$root/artifacts/katl/$version/$file" "$assets/$file"
done
"$cli" config bundle "$root/katl/cluster.yaml" --output "$assets/cluster.katlcfg" \
  --katlos-image-url "$base/assets/$relative/katlos-install-$version-x86_64.squashfs" \
  --katlos-image-metadata "$assets/katlos-install-$version-x86_64.squashfs.json"
digest=$(sha256sum "$assets/cluster.katlcfg" | cut -d ' ' -f1)
while IFS= read -r node; do
  name=$(jq -r .hostname <<<"$node")
  mac=$(jq -r .mac <<<"$node")
  jq -n --arg name "$name" --arg relative "$relative" --arg base "$base" --arg digest "$digest" '
    {id:("katl-"+$name),name:("Install KatlOS "+$name),boot:{
      kernel:("/assets/"+$relative+"/katl-installer.vmlinuz"),
      initrd:["/assets/"+$relative+"/katl-installer.initrd"],
      args:["initrd=katl-installer.initrd","rd.neednet=1","ip=dhcp","console=tty0",
        ("katl.bundle.url="+$base+"/assets/"+$relative+"/cluster.katlcfg"),
        ("katl.bundle.sha256="+$digest),("katl.node="+$name),
        "katl.install.mode=auto","katl.halt-if-installed=1"]}}
  ' > "$out/profiles/katl-$name.json"
  jq -n --arg name "$name" --arg mac "$mac" \
    '{name:$name,profile:("katl-"+$name),selector:{mac:$mac}}' > "$out/groups/$name.json"
done < <(yq -o=json -I=0 '.nodes[]' "$root/katl/nodes.yaml")
echo "Matchbox bundle: $out (contains private node keys; restrict HTTP access and remove after installation)"
