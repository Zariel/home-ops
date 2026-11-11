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

OTBR uses `thread-infra` at `fd74:f571:d3bd:1060::2/64`; Matter.js uses
`matter-controllers` at `fd74:f571:d3bd:1061::2/64`. Both addresses are
allocated in NetBox. Their PVCs, Thread dataset, Matter fabric and existing
MAC addresses are retained. Home Assistant keeps its existing IoT/trusted
attachments and reaches the controller through its Kubernetes Service; its
former IoT RA/RIO learning is disabled.

VyOS learns `/64` RIOs only on VLAN 1100 and only from OTBR's retained
`0a:92:17:bd:44:6e` / `fe80::892:17ff:febd:446e` identity. It ignores PIOs,
default-router announcements and advertised MTUs on that interface. The
OMR prefix remains `fd42:dfb5:24e4:1::/64`; it has no static IoT next hop.
The service-filtered mDNS reflector includes trusted, IoT, OTBR and controller
networks. VyOS 1.4 needs the mixed-address-family mDNS validator patch in the
router repository's preconfiguration boot hook: the stock validator rejects
IPv6-only links in `both` mode even though Avahi supports them. Review that
compatibility patch when upgrading VyOS. Matter UDP is permitted between the
controller and Thread/IoT endpoints, with trusted commissioning access to Thread
and the border agent.
UDP ports are learned from discovery and can include an ephemeral controller
port, so the firewall scopes these flows by endpoint/prefix rather than only
allowing destination port 5540. Both new attachments retain default-drop WAN
policies.

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
   attachments on each node. All six node/VLAN combinations passed 1500-byte
   IPv6 tests on 2026-11-06 after the Katl and Cilium rollout; test namespaces
   and interfaces were removed.
5. Before migrating workloads, back up OTBR's active dataset and both data
   volumes, and apply the VyOS application/discovery policies. Deploy OTBR
   on VLAN 1100 with its retained MAC, then enable the restricted RIO input
   policy. Confirm a live `proto ra` OMR route via OTBR's link-local address
   before removing the old static IoT route. Matter.js depends on OTBR's
   Deployment health; verify all previously available nodes reconnect and
   Home Assistant retains its WebSocket connection after their restarts.
   Check both the learned route and the devices after router configuration
   changes, since gateway HTTP health alone cannot establish Matter health.

For rollback before workload migration, revert these preparation files;
existing workloads keep their IoT attachment. Once workloads have moved,
restore their previous attachments and routing before removing these VLANs
or Cilium bypass entries.

## North star: VXLAN pod attachments over a routed underlay

Consider moving VLAN-backed Multus pod attachments to VXLAN-backed Linux
bridges as the node fabric moves toward routed, dual-homed links. This would
carry the required Ethernet networks over IP and remove their dependency on
VLAN trunks reaching every eligible Kubernetes node. Preserve separate
broadcast domains and the existing IPv6 addressing and gateway policy.

Katl would own the host bridges and VXLAN endpoints; Multus would attach pods
through the bridge CNI. Linux on the nodes and VyOS could terminate tunnels,
with the ICX switches routing the outer packets. Stable, routable endpoint
addresses would let routing handle physical-link failover. A small deployment
could use static peer and flood lists; EVPN is a later option for distributing
endpoint reachability as the fabric grows.

The node underlay already uses MTU 9000. Before a migration, verify the MTU
across the complete tunnel path and account for encapsulation. Validate
multicast replication, mDNS, ND/RA, Cilium interaction and link/node failure
behavior, including OTBR's OMR advertisements. Keep this as a future direction
to evaluate alongside the routed fabric work.

References: [macvlan CNI](https://www.cni.dev/plugins/current/main/macvlan/),
[static IPAM](https://www.cni.dev/plugins/current/ipam/static/), and
[Cilium VLAN support](https://docs.cilium.io/en/stable/configuration/vlan-802.1q/).
