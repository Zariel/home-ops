#!/usr/bin/env bash
set -euo pipefail

output=$(realpath -m -- "${1:?usage: build-sysext.sh OUTPUT.raw}")
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

repo=https://dl.fedoraproject.org/pub/fedora/linux/updates/45/Everything/x86_64/Packages

extract_rpm() {
  local name=$1 package=$2 checksum=$3
  curl --fail --silent --show-error --location "$repo/$package" -o "$work/$name.rpm"
  printf '%s  %s\n' "$checksum" "$work/$name.rpm" | sha256sum --check --status
  mkdir "$work/$name"
  bsdtar -xf "$work/$name.rpm" -C "$work/$name" ./usr
}

extract_rpm bluez b/bluez-5.88-1.fc45.x86_64.rpm 89cf1c66846d19819be4584f1e9d67230fa8d715297c768064e98b11c6c3d350
extract_rpm glib2 g/glib2-2.90.1-1.fc45.x86_64.rpm b60cf429338776312f0937ac512ecdb595b00c0642d22075c31f6c86410f46d0
extract_rpm firmware m/mt7xxx-firmware-20261019-1.fc45.noarch.rpm 05e9d178d762f20815f0751c2c3a49987d86f1f243c59184efe50679bc2dd515

payload="$work/payload"
mkdir "$payload"
(
  cd "$work/bluez"
  cp -a --parents usr/bin/{bluetoothctl,btmgmt} usr/libexec/bluetooth/bluetoothd \
    usr/lib/systemd/system/bluetooth.service usr/share/dbus-1/system.d/bluetooth.conf \
    usr/share/dbus-1/system-services/org.bluez.service usr/share/licenses/bluez "$payload"
  cd "$work/glib2"
  cp -a --parents usr/lib64/libglib-2.0.so.0* usr/share/licenses/glib2 "$payload"
  cd "$work/firmware"
  cp -a --parents usr/lib/firmware/mediatek/BT_RAM_CODE_MT{7922_1_1,7961_1_2,7961_1a_2}_hdr.bin.xz \
    usr/share/licenses/mt7xxx-firmware "$payload"
)

install -d "$payload/usr/lib/extension-release.d"
cat >"$payload/usr/lib/extension-release.d/extension-release.hollywoo-bluetooth" <<'EOF'
ID=katlos
SYSEXT_LEVEL=katl-runtime-1
SYSEXT_ID=hollywoo-bluetooth
ARCHITECTURE=x86-64
EOF

mksquashfs "$payload" "$output" -noappend -all-root -mkfs-time 0 -all-time 0 -processors 2 -quiet
