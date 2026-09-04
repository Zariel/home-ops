---
apiVersion: v1alpha1
kind: HostnameConfig
auto: "off"
hostname: {{ .Node.Host }}
---
apiVersion: v1alpha1
kind: UnattendedInstallConfig
provisioning:
  diskSelector:
    match: disk.wwid == "{{ .Node.Data.installDiskWWID }}"
  wipe: false
---
# connectx-4
apiVersion: v1alpha1
kind: EthernetConfig
name: enp1s0f0np0
rings:
  rx: 8192
  tx: 8192
channels:
  combined: 20
features:
  rx-udp-gro-forwarding: off
---
# connectx-4
apiVersion: v1alpha1
kind: EthernetConfig
name: enp1s0f1np1
rings:
  rx: 8192
  tx: 8192
channels:
  combined: 20
features:
  rx-udp-gro-forwarding: off
---
apiVersion: v1alpha1
kind: BondConfig
name: bond0
links:
  - enp1s0f0np0
  - enp1s0f1np1
addresses:
  - address: {{ .Node.Data.bond0Address }}
routes:
  - gateway: {{ .Node.Data.bond0Gateway }}
bondMode: active-backup
miimon: 100
mtu: 9000
---
apiVersion: v1alpha1
kind: VLANConfig
name: bond0.20
parent: bond0
vlanID: 20
mtu: 1500
---
apiVersion: v1alpha1
kind: VLANConfig
name: bond0.40
parent: bond0
vlanID: 40
mtu: 1500
---
apiVersion: v1alpha1
kind: VLANConfig
name: bond0.300
parent: bond0
vlanID: 300
addresses:
  - address: {{ .Node.Data.storageAddress }}
mtu: 9000
---
apiVersion: v1alpha1
kind: VLANConfig
name: bond0.1100
parent: bond0
vlanID: 1100
mtu: 1500
---
apiVersion: v1alpha1
kind: BondConfig
name: bond1
links:
  - enp87s0
  - enp90s0
addresses:
  - address: {{ .Node.Data.managementAddress }}
routes:
  - gateway: 10.1.1.1
    table: "100"
bondMode: active-backup
miimon: 100
mtu: 1500
---
apiVersion: v1alpha1
kind: VRFConfig
name: vrf-mgmt
links:
  - bond1
table: "100"
up: true
---
apiVersion: v1alpha1
kind: UserVolumeConfig
name: local-hostpath
provisioning:
  minSize: 1GiB
  diskSelector:
    match: disk.wwid == "{{ .Node.Data.localHostpathWWID }}"
filesystem:
  type: xfs
