# Hollywoo on Katl

This replaces the Talos source configuration for the three MS-01s with KatlOS
2026.9.0-beta.11 and Kubernetes v1.36.4. `cluster.yaml` is the retained node
configuration; `version` pins both the CLI and OS/PXE assets. The tasks use that
release's CLI, not a workstation-global version. No cluster changes are made by
checking out this bookmark or validating/bundling its configuration.

Beta.11 supports the directory-backed network file sets and requires durable
management secrets. `spec.managementIdentity` references the ignored
`.local/management-secrets.yaml`; create it explicitly for a new cluster before
compiling a bundle, and retain it across reinstalls.

## Retained configuration

All three nodes are control planes and accept workloads. Node names, `/31`
Kubernetes addresses, Pod CIDR `172.20.0.0/16`, Service CIDR `172.21.0.0/16`,
CoreDNS `172.21.0.10`, and API name `k8s.cbannister.casa:6443` are retained.

The shared `network` file set includes `files/systemd/network` recursively.
Relative paths become paths under `/etc/systemd/network`, so adding a shared
native file or drop-in does not need another mapping in `cluster.yaml`. Each
node's `addresses` set keeps its three small address and route drop-ins inline
using `files[].content`, alongside the rest of that node's configuration.

Native networkd files implement the ConnectX-4 active-backup `bond0` (MTU 9000),
VLANs 20/40/300/1100, the secondary active-backup `bond1`, and management VRF
(table 100). Katl management uses the existing routed `10.254.1.1/.3/.5`
addresses, not the interfaces inside the management VRF. The ConnectX link files
match the PCI slots implied by the existing predictable interface names; verify
those slots and the generated names from the installer before committing to a
bare-metal install.

Static `/etc/hosts` entries preserve resolution of the three node names.
DNS remains `172.53.53.53`; systemd-timesyncd is started through a native target
drop-in and uses `10.254.254.1`. CPU sysfs settings, network sysctls, hugepages,
udev permissions for ZBT2, NFS options, containerd options, kubelet settings,
control-plane resources, scheduler policy, and API audit policy are retained.
SSH authorizes the current `chris@gaming` public key; review it before install.

The native kubeadm configuration disables kube-proxy and CoreDNS installation;
GitOps retains Cilium and CoreDNS ownership. The named `cilium` file set supplies `/etc/sysctl.d/90-cilium.conf`;
reverse-path filtering is explicit cluster policy. Cilium still uses Katl's local API
proxy at `127.0.0.1:7445`. Its sysctl-file writer is disabled for Katl's immutable
`/etc`. The API VIP Service now selects kubeadm's `component: kube-apiserver`
label. Cilium continues to advertise `10.45.0.100`; Katl does not also own or
advertise that address. Initial bootstrap uses a direct node endpoint until
Cilium/BGP is established, then the task switches the operator kubeconfig to
the stable DNS endpoint.

System and kernel logs move from Talos UDP receivers to persistent journald and
the Vector agent's separate Katl stream on TCP 6005. The agent uses the Debian
Vector image because the distroless image lacks journalctl. Pod logging stays
on the existing TCP 6000 stream. Tuppr and its Talos/Kubernetes upgrade resources
are removed; OS and Kubernetes upgrades use the Katl tasks below.

## Disks and backup boundary

The three system disk selectors and three local-hostpath selectors are derived
from the existing NVMe EUI identities. Local-hostpath remains XFS mounted at
`/var/mnt/local-hostpath`, matching OpenEBS. Each selected local-hostpath disk
has `wipe: true`, for the planned fresh install and restore. Existing signatures
require a separate explicit wipe acknowledgement from Katl; the PXE bundle does
not bypass that check. Rook's three dedicated Ceph device selectors are unchanged
and are not Katl-managed volumes.

Before wiping, verify the VolSync backups and restore credentials are available
independently of this cluster. Preserve the previous Talos configuration,
encrypted secrets, and local talosconfig from `main`/Git history outside the
machines being rebuilt. If preserving a local-hostpath filesystem instead,
change that node's volume to a partition selector and `wipe: false` before
compilation; do not try to mount an existing partition as a whole disk.

## Prepare and inspect

```sh
nix develop
# Download matching CLI and loose PXE artifacts, and verify checksums.
task katl:download
task katl:validate
task katl:resolve node=k8s-0
task katl:resolve node=k8s-1
task katl:resolve node=k8s-2
# Once, for a new cluster only; refuses to overwrite existing secrets.
task katl:management:identity
task katl:identity
# Back up both katl/.local/management-secrets.yaml and
# katl/.local/hollywoo-kubernetes.katlkey off-cluster.
# Neither belongs in Git or public PXE storage.
```

`katl/.local`, `*.katlkey`, `*.katlcfg`, and `artifacts/` are ignored. Generated
bundles contain private node management keys. The management secrets and
Kubernetes identity serve different purposes; a compiled bundle is not a
management authority backup. Existing Talos CA material is not automatically
converted.

For nodes already installed with an older Katl release, preserve their existing
authority instead of running `katl:management:identity`. Export it using the
original configuration without `spec.managementIdentity`:
`katlctl management identity export --config ORIGINAL_CONFIG --output "$PWD/katl/.local/management-secrets.yaml"`.
Use the beta.11 CLI for this command. It updates the original configuration's
reference as well. Restore an existing project secrets backup directly to the
referenced path with mode 0600. Missing credentials must not be replaced with a
new authority for installed nodes.

## PXE/install

```sh
MATCHBOX_URL=http://10.5.0.8 task katl:matchbox:bundle
# Inspect artifacts/matchbox-katl/{profiles,groups} and the three MACs first.
task katl:matchbox:push destination=vyos@gateway:/config/containers/matchbox/
```

Publishing uses `rsync --delete` against the explicit destination. Use it only
for the dedicated Matchbox tree after reviewing which existing profiles it
replaces. Serve the bundle only on the trusted provisioning network and make it
readable by the Matchbox service account; generated files are private by default.
Remove the HTTP-accessible `.katlcfg` after installation.

The installer relies on provisioning-network DHCP to reach Matchbox; the native
bonds, static addresses, and VRF apply to the installed OS. The existing node
MACs select `katl.node` explicitly. The installed-disk guard prevents reinstall
loops on Katl disks; it does **not** protect a Talos disk from the first install.
PXE auto-install therefore becomes destructive when these profiles are booted.

If a data-disk signature blocks auto-install, inspect the inventory and use
`task katl:install node=k8s-0 -- --acknowledge-storage-wipe k8s-0/local-hostpath`
only after confirming that exact disk may be erased. Repeat for the appropriate
node. Use `--endpoint ADDRESS` for an installer's temporary DHCP address.

## Bootstrap and restore

Ensure this change is present on the branch Flux follows (`main`) before running
Flux bootstrap. Until then, `main` still describes Talos and would restore Tuppr
and the old VIP selector. This bookmark is not deployed automatically.

```sh
task katl:status
task bootstrap:katl
kubectl get nodes -o wide
kubectl -n kube-system get endpointslice -l kubernetes.io/service-name=kube-vip
kubectl get --raw=/readyz
kubectl -n rook-ceph get cephcluster
```

The bootstrap task enrolls nodes, uses the backed-up Kubernetes identity,
bootstraps kubeadm, installs Cilium/BGP, then CoreDNS, CRDs, and Flux. It writes
`kubeconfig.yaml`. Beta.11 authenticates trusted reinstalls using the retained
management authority and node name, then refreshes the disposable workstation
context automatically. Preserve the same management secrets for replacement
nodes; an unrelated authority cannot authenticate the installed nodes.

Verify routing/BGP, DNS, API VIP access, Rook provisioning, a restored VolSync
volume, and real workload reads/writes before declaring the migration complete.
Hardware link settings, CPU sysfs availability, management VRF reachability,
time synchronization, and journal collection still require bare-metal checks.

## Upgrades and differences

```sh
task katl:upgrade node=k8s-0 -- --plan
task katl:upgrade node=k8s-0
# Upgrade every configured node sequentially to an explicit release.
task katl:cluster:upgrade version=2026.9.0-beta.14
task katl:kubernetes:upgrade -- --plan
task katl:kubernetes:upgrade
```

Renovate proposes updates to `katl/version` and the Kubernetes version in
`cluster.yaml`; these source updates do not themselves mutate nodes. Review
minor-version upgrade constraints and apply through Katl. No automatic
in-cluster OS upgrader replaces Tuppr in this change.

`katl:cluster:upgrade` uses the pinned CLI from `katl/version` and upgrades to
the explicitly supplied release. It plans all nodes before starting, then
checks every CephCluster and CNPG Cluster before each node and after recovery.
The checks require Ceph `HEALTH_OK`, all OSDs up and in, clean placement groups,
CNPG Ready with all instances healthy, working archiving and a successful backup
within 48 hours where configured, and streaming replicas within one WAL segment
of the primary. If the next node hosts a CNPG primary, the task uses
`kubectl cnpg promote` to switch it to a replica on another node before draining.
The development shell includes that plugin. A failed upgrade leaves its node
cordoned and stops the run; inspect and recover it before retrying. The workflow
requires the Rook toolbox deployment in each Ceph cluster namespace.

Talos discovery/API access, OOMConfig, extension names, and Talos-specific
kernel logging/audit arguments have no direct Katl translation. Katl provides
native management, in-tree GPU/MEI drivers and firmware, and Intel microcode.
Kubeadm requires its static-pod manifest directory, so Talos's disable-manifests
setting is intentionally omitted. API audit output goes to the API container's
stdout and through normal pod-log collection. Host security follows Katl's
runtime defaults apart from the explicitly retained kernel arguments.

References: [Katl configuration](https://github.com/katl-dev/katl/blob/v2026.9.0-beta.11/docs/installing.md),
[management secrets](https://github.com/katl-dev/katl/blob/v2026.9.0-beta.11/docs/operations/access.md),
[kubeadm native configuration](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/),
and [Vector journald input](https://vector.dev/docs/reference/configuration/sources/journald/).
