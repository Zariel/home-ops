#!/usr/bin/env bash
set -euo pipefail

for device in /dev/kvm /dev/vhost-vsock /dev/net/tun; do
  if [[ ! -r "$device" || ! -w "$device" ]]; then
    echo "error: VM-test runner requires read/write access to $device" >&2
    exit 1
  fi
done

mkdir -p /run/libvirt /var/log/libvirt /var/lib/libvirt/images
virtlogd --daemon
virtlockd --daemon
libvirtd --daemon

timeout 30 bash -c 'until virsh --connect qemu:///system uri >/dev/null 2>&1; do sleep 1; done'

# Each ephemeral pod owns its libvirt network and disks; no host sockets or
# persistent libvirt state are shared between workflow jobs.
virsh --connect qemu:///system net-define /etc/libvirt/qemu/networks/default.xml
virsh --connect qemu:///system net-start default
virsh --connect qemu:///system pool-define-as default dir --target /var/lib/libvirt/images
virsh --connect qemu:///system pool-start default

dockerd --host=unix:///run/docker.sock > /var/log/dockerd.log 2>&1 &
timeout 60 bash -c 'until docker info >/dev/null 2>&1; do sleep 1; done' || {
  cat /var/log/dockerd.log >&2
  exit 1
}

exec "$@"
