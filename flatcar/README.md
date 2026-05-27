# Flatcar kubeadm foundation

This tree builds the host and Kubernetes foundation only:

- Flatcar installer and node Ignition merge roots
- systemd-networkd management VRF, Kubernetes bond, Multus VLANs, and Rook VLAN
- kubeadm init/join configs for three control-plane nodes
- containerd 2.3 from sysext-bakery, with Flatcar's built-in Docker/runtime
  sysexts disabled
- host BIRD with Cilium iBGP and OSPF on `bond0`
- API anycast `10.254.254.100/32` advertised only while local `/readyz` passes

It intentionally does not bootstrap Flux or application workloads.

## Render

```sh
nix develop -c task flatcar:generate:check
nix develop -c task flatcar:generate
```

Pass `config=...` to render a separate lab config without changing the
physical-node config:

```sh
nix develop -c task flatcar:generate:check config=flatcar/config.proxmox-lab.pkl
nix develop -c task flatcar:matchbox:bundle config=flatcar/config.proxmox-lab.pkl
```

`generate:check` uses throwaway local values and does not write persistent
artifacts. Normal rendering reads these fields from
`op://Kubernetes/flatcar-kubeadm-hollywoo`:

- `kubeadm-token`
- `kubeadm-certificate-key`
- `kubernetes-ca-crt`
- `kubernetes-ca-key`
- `ssh-public-key`

Generate and populate them with:

```sh
nix develop -c flatcar/scripts/populate-kubeadm-secrets.sh --create-vault
```

If the item already exists, rerun with `--force` to rotate the generated
values. To use an existing operator SSH key instead of generating one:

```sh
nix develop -c flatcar/scripts/populate-kubeadm-secrets.sh \
  --ssh-public-key ~/.ssh/id_ed25519.pub
```

Do not rotate these casually after a cluster has bootstrapped:

- `kubernetes-ca-crt` and `kubernetes-ca-key` define the cluster CA. Changing
  them is effectively a new trust root; existing kubelets, apiserver certs,
  kubeconfigs, and joins will not automatically trust the new CA.
- `kubeadm-token` is only needed for future joins while it is valid in the
  cluster. Changing the 1Password value alone does not create or revoke tokens
  inside an already running cluster.
- `kubeadm-certificate-key` is used by kubeadm upload-certs/join flow. Changing
  the 1Password value alone does not re-encrypt or re-upload certs in an
  already running cluster.
- `ssh-public-key` only affects future rendered Ignition. Existing nodes keep
  the keys already written to disk unless managed separately.

All rendered output is written under `artifacts/flatcar/`, which is ignored.
The matchbox data directory is rendered at `artifacts/flatcar/matchbox/`.

Static Butane components live in `flatcar/butane/components/` and are
merged into per-node Ignition:

- `host.bu`
- `updates.bu`
- `bird.bu`

Cluster-wide values and node facts live in `flatcar/config.pkl`. Shared Pkl
types/helpers live in `flatcar/config.schema.pkl`. The renderer evaluates Pkl
to JSON, then normalizes that data before rendering Butane, kubeadm, and
matchbox artifacts.

Sysext-bakery version and download integrity pins are declared as `bakery`
entries:

- `name`
- `version`
- `sha`

Bakery-backed Butane components are rendered from
`flatcar/templates/butane/components/*.bu.j2` because they need those pins. The
renderer exposes each bakery entry by name and adds generic `sysext`, `minor`,
and `arch` fields from the supplied values.

Shared host shapes are declared as `roles` in `flatcar/config.pkl`.
Nodes opt in with `roles { "ms01" }`. Role and node networkd config is rendered
directly into `/etc/systemd/network/<name>` from generic `networkd.files`
entries:

- `sections[]` emits repeated `[Section]` blocks.
- scalar settings emit one `Key=value` line.
- array settings emit repeated `Key=value` lines.
- `contents = """..."""` can be used as an escape hatch for raw networkd file
  contents.
- string values may reference render data such as `{{ node.bond_ip }}`.

Role-level `wait_online` config controls system readiness separately from
kubelet readiness. `wait_online.networkd` feeds
`systemd-networkd-wait-online.service`, while `wait_online.kubelet` feeds the
kubelet drop-in `ExecStartPre`.

`updates.bu` stages Flatcar foundation sysext updates and writes
`/run/reboot-required` when an applied extension changes. It does not reboot the
host; run kured or another cluster-level coordinator to drain and reboot nodes.

The renderer writes full selector-scoped Ignition files for matchbox:

- `artifacts/flatcar/matchbox/ignition/installers/<node>.ign`
- `artifacts/flatcar/matchbox/ignition/nodes/<node>.ign`

Templates are only used locally where values are secret or generated:

- `flatcar/templates/butane/components/ssh.bu.j2`
- `flatcar/templates/butane/installers/installer.bu.j2`
- `flatcar/templates/butane/nodes/node.bu.j2`
- `flatcar/templates/butane/secrets/kubeadm.bu.j2`
- `flatcar/templates/kubeadm/*.yaml.j2`
- matchbox group/profile JSON

Each node group has metadata for hostname, install disk, configured extra
disks, management IP, bond IP/gateway, Rook VLAN IP, and BIRD router ID.
Kubeadm tokens, certificate keys, CA material, and SSH access material are not
put in matchbox metadata.

Per-node `extra_disks` entries specify:

- `selector`: disk path or stable `/dev/disk/by-id/...` selector
- `mount_path`: where the installed node mounts it
- `filesystem`: filesystem Ignition creates on the selected device

The generated groups separate install and installed-node Ignition:

- The installer group matches the node MAC only, so stock matchbox
  `/boot.ipxe` can chain to `/ipxe` and select `<node>-installer`.
- `stage=node` uses `<node>-node` and `nodes/<node>.ign`

The installer unit fetches the node Ignition with `stage=node`, verifies that
each configured extra disk resolves to a different device than the OS disk,
installs Flatcar to disk, then reboots. The installed-node Ignition config uses
`storage.disks` and `storage.filesystems` with `wipe_table`, `wipe_filesystem`,
and `with_mount_unit` to format and mount extra disks. This is intentionally
destructive for each configured extra disk.

## Operator flow

1. Build and publish the matchbox bundle:

   ```sh
   nix develop -c task flatcar:matchbox:push
   ```

   This renders Ignition with real bootstrap material, downloads the Flatcar
   PXE kernel/initrd into `assets/flatcar/<version>/`, updates
   `assets/flatcar/current`, and pushes `artifacts/flatcar/matchbox/` as the
   matchbox data directory. Override `host=`, `dest=`, `installers=`,
   `FLATCAR_CHANNEL`, `FLATCAR_VERSION`, or `FLATCAR_BASE_URL` when needed.
   `installers=` defaults to `all`; set it to a comma-separated node list or
   `none` to control which `*-installer` groups are published.

2. Let nodes boot from disk for normal operation.
3. After `k8s-0` initializes, run the Kubernetes foundation bootstrap:

   ```sh
   nix develop -c task bootstrap:flatcar controller=10.1.10.10
   ```

   Pass `apiServer=` if the operator machine should use a different API URL
   than `https://10.254.254.100:6443`.
4. Confirm all control-plane nodes join, Cilium is ready, CoreDNS resolves, and
   `10.254.254.100:6443` is reachable before any Flux/app recovery.

## Proxmox lab

Disposable Proxmox VMs are managed by `flatcar/scripts/proxmox-lab.py`.
`flatcar/proxmox-lab.pkl` is intentionally ignored; use
`flatcar/proxmox-lab.example.pkl` as the tracked shape for the local lab
inventory. `flatcar/config.proxmox-lab.pkl` is also ignored; the tracked
`flatcar/config.proxmox-lab.example.pkl` is a renderable three-node Flatcar
lab config with VM MAC addresses matching the Proxmox example.

```sh
task flatcar:lab:plan
task flatcar:lab:up
task flatcar:lab:destroy
task flatcar:lab:recreate
task flatcar:lab:up dryRun=true
```

The helper uses SSH to run `qm` on the Proxmox node. It creates OVMF/q35 VMs
with virtio NICs, a primary SCSI disk, optional extra SCSI disks, and disk-first
boot order with PXE fallback. Match the VM MAC addresses to the Flatcar lab
config rendered into matchbox.

## One-time PXE boot

For UEFI hosts, each node has a `flatcar-pxe-once.service` unit that uses
`efibootmgr` to set PXE as the next boot only, then reboots. This avoids
changing the permanent firmware boot order:

```sh
task flatcar:pxe:list node=k8s-0
task flatcar:pxe-once node=k8s-0 reboot=true
```

`node=` is resolved from `flatcar/config.pkl` `management_ip` and uses that
node's configured `mac` to select the matching UEFI PXE entry. Use `host=` to
target an address directly, `mac=58:47:ca:78:d2:44` to choose the PXE interface
by MAC, or `entry=0007` to start `flatcar-pxe-once@0007.service` directly.
