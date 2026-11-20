#!/usr/bin/env bash
set -euo pipefail

go version
kubectl version --client
systemd-dissect --version
for tool in qemu-img sfdisk mformat mcopy truncate sha256sum awk realpath; do
  command -v "$tool"
done
test -r "$KATL_OVMF_CODE"
test -r "$KATL_OVMF_VARS"
ip -4 address show dev virbr0 | grep -F '10.77.0.1/24'

# Exercise the same nested privilege boundary used by Katl's mkosi builder.
docker run --rm --privileged docker.io/library/alpine:3.23.2 \
  sh -ec 'mount -t tmpfs tmpfs /mnt; touch /mnt/build-check; test -f /mnt/build-check'

cat > /tmp/runner-check.xml <<EOF
<domain type="kvm">
  <name>runner-check</name>
  <memory unit="MiB">256</memory>
  <vcpu>1</vcpu>
  <features><acpi/></features>
  <os>
    <type arch="x86_64" machine="q35">hvm</type>
    <loader readonly="yes" type="pflash">$KATL_OVMF_CODE</loader>
    <nvram template="$KATL_OVMF_VARS">/var/lib/libvirt/images/runner-check.fd</nvram>
  </os>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <interface type="network">
      <source network="default"/>
      <model type="virtio"/>
    </interface>
    <vsock model="virtio"><cid auto="yes"/></vsock>
  </devices>
</domain>
EOF

virsh --connect qemu:///system create /tmp/runner-check.xml
trap 'virsh --connect qemu:///system destroy runner-check' EXIT
virsh --connect qemu:///system qemu-monitor-command runner-check \
  '{"execute":"query-kvm"}' | jq --exit-status '.return.enabled == true'
