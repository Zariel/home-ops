# Matter and Thread attachments

These IPv6-only macvlan networks use dedicated VLANs routed by VyOS. The
host bond keeps its 9000-byte MTU; these VLANs and pod attachments use 1500,
matching the gateways. Katl owns the host VLAN interfaces, Multus owns pod
interfaces, and Cilium permits the VLAN tags on `bond0`.

| Attachment in `kube-system` | Host parent | IPv6 prefix | Gateway |
| --- | --- | --- | --- |
| `thread-infra` | `bond0.1100` | `fd74:f571:d3bd:1060::/64` | `fd74:f571:d3bd:1060::1` |
| `matter-controllers` | `bond0.1101` | `fd74:f571:d3bd:1061::/64` | `fd74:f571:d3bd:1061::1` |

The host interfaces are unnumbered, with link-local addressing and RA
acceptance disabled. Pods retain their normal Cilium attachment for cluster
services and IPv4 connectivity. Each new attachment installs an explicit
IPv6 default route through its VyOS gateway; controller routing does not
depend on learning RAs. OTBR still needs its own infrastructure-link IPv6
configuration for border routing.

Static IPAM takes the pod address from the Multus annotation's `ips` field.
Allocate each address in NetBox before using it, and include its `/64` mask.
For example, select `thread-infra` in namespace `kube-system` for OTBR, or
`matter-controllers` in that namespace for the controller. Keep the interface
name `net1` used by both applications. The definitions intentionally contain
no shared pod address, so they can serve different pods without duplicating
an address. Static IPAM does not coordinate allocations across nodes; retain
the singleton applications' `Recreate` deployment strategy during migration.

## Rollout

This change prepares host configuration and attachment definitions. The
OTBR and Matter.js deployments still use `iot`; they are not migrated by
adding these definitions. No VXLAN devices or tunnels are configured.

1. Plan and apply the reviewed Katl host configuration through the normal
   operator workflow. Check `bond0.1100` and `bond0.1101` exist and are up on
   every eligible node. Network configuration belongs to Katl, so a Flux
   dependency cannot establish that the host interfaces are ready.
2. Reconcile the Cilium values through GitOps. Its VLAN bypass list becomes
   `20,40,300,1100,1101`; verify the regenerated datapath accepts both new
   VLANs. The Helm configuration already requests pod rollout when values
   change. These five VLANs reach Cilium's documented bypass-list limit.
3. Reconcile `multus-networks` and check the two attachment definitions in
   `kube-system`. The ICX must carry both VLANs to VyOS and each node; the
   VyOS gateways and ICX tagging were provisioned separately.
4. Test IPv6 neighbor discovery and gateway reachability from temporary
   attachments on each node. This preparation has not performed that rollout
   or those live tests.
5. Prepare the application firewall rules and selective discovery on VyOS,
   allocate pod addresses, then migrate the workloads separately. Preserve
   the Thread dataset and current OMR prefix `fd42:dfb5:24e4:1::/64`. Keep
   the current OMR static route while OTBR is on IoT. Change its next hop
   during OTBR migration; enable restricted RIO learning only after OTBR is
   on VLAN 1100. Keep RA learning disabled on IoT. The current gateway
   baseline drops application traffic between the new zones, so gateway
   reachability alone does not establish that Matter is ready.

For rollback before workload migration, revert these preparation files;
existing workloads keep their IoT attachment. Once workloads have moved,
restore their previous attachments and routing before removing these VLANs
or Cilium bypass entries.

References: [macvlan CNI](https://www.cni.dev/plugins/current/main/macvlan/),
[static IPAM](https://www.cni.dev/plugins/current/ipam/static/), and
[Cilium VLAN support](https://docs.cilium.io/en/stable/configuration/vlan-802.1q/).
