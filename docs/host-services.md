# Host service addressing

NetBox is the allocation authority. The [host-service pool](https://netbox.cbannister.xyz/ipam/prefixes/131/)
reserves `10.5.0.0/16` for IPv4 services
owned by individual hosts. Allocate one `/26` per host, and record the owning
host and each service address before configuring them. A `/26` provides 64
addresses; the pool holds 1,024 host blocks. Allocate blocks as needed rather
than preassigning every existing host or embedding a host-number formula.

Each application with a routed unicast listener gets its own `/32` within its
host's block. DNS names identify the service and host. The host advertises only
its `/26` to the internal fabric. Do not advertise the entire `/16`: another
host must be able to originate its own block through a different next hop.
BGP advertisements describe host ownership, not application health. Restarting
an application leaves the block advertised; losing the host or its routing
session withdraws the path. This does not provide application failover.

## Address ownership

| Purpose | Allocation | What belongs here |
| --- | --- | --- |
| Host-owned application endpoints | `10.5.0.0/16`, `/26` per host | Per-host NTP, TFTP, HTTP apps, exporters and authoritative DNS endpoints |
| Shared infrastructure VIPs | Existing `10.254.253.0/24` | Logical services whose address survives a host change, including DNS resolver anycast `10.254.253.53` |
| Device identities | Existing `10.254.254.0/24` subdivisions | Router IDs, host management identities and loopback BGP peering where configured |
| Transit and client networks | Existing NetBox allocations | BGP link endpoints, default routers, VRRP and VLAN addressing |
| Kubernetes workload VIPs | Existing `10.45.0.0/24` | Cilium LoadBalancer addresses |

SSH and SFTP administer a host and use its identity or management addresses.
They do not need a separate address merely because applications have one.
BGP router IDs and BGP session endpoints are separate concepts: the gateway's
router ID remains `10.254.254.1`; the core session uses `10.254.0.0/31`.
DHCP broadcast sockets, mDNS reflection, IPv6 router advertisements and the
WireGuard WAN listener remain on the interfaces and addresses their protocols
require. Unix sockets and localhost-only backends do not consume service IPs.

Choose ownership before allocating a service. A single host's Chrony instance
belongs in its host block. A future shared NTP service could have a VIP in the
shared pool and independently managed host backends. Do not put a host's
`/26` in the shared VIP pool or announce another host's block as a shortcut.
Service addresses are routing and firewall policy identifiers; they do not
replace process isolation or authentication.

## Gateway allocation

The gateway's logical role takes the [reserved `10.5.0.0/26` block](https://netbox.cbannister.xyz/ipam/prefixes/132/). VyOS and its NixOS replacement
are successive owners of the same block; do not run both with these addresses
or advertise the block from both routers during cutover.

| Service | Address | DNS name | Listener |
| --- | --- | --- | --- |
| Matchbox | `10.5.0.8/32` | `matchbox.cbannister.casa` | TCP 80 |
| TFTP | `10.5.0.9/32` | `gateway-tftp.cbannister.casa` | UDP 69 and tracked transfer replies |
| NTP | `10.5.0.10/32` | `gateway-ntp.cbannister.casa` | UDP 123 |
| Host metrics | `10.5.0.11/32` | `gateway-metrics.cbannister.casa` | TCP 9100 |
| DHCP DNS primary | `10.5.0.53/32` | `gateway-dhcp-dns.cbannister.casa` | TCP/UDP 53, DNS replicas only; NixOS |

NixOS assigns the application addresses as `/32`s on loopback. Networkd owns
an unreachable route for the `/26`, and FRR originates that exact prefix.
Unallocated addresses terminate at the owning host instead of following a
WAN default route. Removing the summary route withdraws the announcement;
removing one application address does not withdraw other applications.
The firewall still selects the individual destination address, port and client
zone. Owning the block does not grant every client access to every service.

## Kubernetes gateway consumers

The gateway migration updates these consumers in this repository:

| Consumer | Desired setting | Configuration |
| --- | --- | --- |
| All three Katl nodes, networkd-provided NTP | `10.5.0.10` | `katl/files/systemd/network/20-bond0.network` |
| All three Katl nodes, systemd-timesyncd | `10.5.0.10`, no fallback | `katl/files/systemd/timesyncd.conf.d/50-hollywoo.conf` |
| VictoriaMetrics gateway exporter scrape | `gateway-metrics.cbannister.casa:9100` (`10.5.0.11`) | `k8s/apps/monitoring/victoria-metrics/cluster/scrapeconfigs/node-exporter.yaml` |

Katl's shared host file set supplies both NTP files to every node. Updating a
Kubernetes manifest cannot change those host files: they require a Katl host
configuration apply. The scrape target is managed separately through Flux.

CoreDNS continues forwarding to the shared resolver VIP `10.254.253.53`.
Matchbox remains `10.5.0.8`. Cilium BGP peers retain the core-switch transit
endpoints `10.254.1.0`, `.2` and `.4`; the API LoadBalancer retains `10.45.0.100`.
The DNS probes for `gateway.cbannister.casa` still check the device identity.
Generic alert-rule fixtures using that hostname do not configure scrape targets.

The gateway endpoints and DNS records were deployed on 2026-11-14. Katl applied
the NTP files to each node sequentially in live mode. Each node's saved files,
synchronization marker and systemd-timesyncd journal confirmed `10.5.0.10`, and
all three nodes remained Ready. The new metrics hostname resolved to
`10.5.0.11` and returned HTTP 200 from VMAgent before publishing the scrape
change through Flux.

Use the repository shell and task wrapper to validate and preview host changes:

```sh
nix develop --command task katl:validate
nix develop --command task katl:apply -- --plan --mode live
kubectl --kubeconfig=./kubeconfig kustomize k8s/apps/monitoring/victoria-metrics/cluster/scrapeconfigs
```

## Beefchunk gateway consumer

Beefchunk's NTP client now uses `10.5.0.10`. On 2026-11-14, its association
reached synchronized state, its clock referenced the new address, and the
setting was saved with `write memory`. `show configuration` confirmed it in
startup configuration. Its management identity and SNMP scrape address remain
`10.254.254.10`.

The switch configuration change was:

```text
enable
configure terminal
ntp
server 10.5.0.10
no server 10.254.254.1
exit
end
write memory
```

Verify with `show ntp associations`, `show ntp status`, and
`show configuration | include 10.5.0.10`. The core's route lookup also confirmed
`10.5.0.0/26` via `10.254.0.0` on `ve 3001`; the old gateway `/24` was withdrawn.

## Staged migration

The service-address migration is live on VyOS as of 2026-11-14. The NixOS OS
replacement remains a separate cutover. The three DNS VMs serve the new records
from a DNS-only revision, without enabling the future NixOS DHCP DNS primary.

NetBox records the `/26` and `.9` through `.11` as active, with those service
addresses assigned to VyOS loopback. The bridge address is `10.5.0.1/26`.
The legacy `/24` is reserved as an allocation hold during cutover; it is no
longer a live bridge prefix or BGP announcement. `.53` remains reserved for
NixOS. Matchbox retains its existing active `.8` endpoint.

The ordering below documents the migration and remaining NixOS cutover steps.
Inspect current state before repeating any completed step.

1. Reserve the parent pool, gateway block and new addresses in NetBox. Matchbox
   already uses `.8`; record it as an existing active endpoint. Leave the live
   legacy `10.5.0.0/24` container network and `10.5.0.1/24` record intact until
   their replacement is verified. Do not allocate other host blocks inside
   that legacy `/24` while it is still active; use the next free block outside
   it for another host.
2. Deploy the service DNS records from the gateway Nix branch to the three DNS
   VMs. Keep `gateway.cbannister.casa` pointing at `10.254.254.1`.
3. Review and apply the VyOS configuration changes during a maintenance window.
   The container bridge shrinks to `/26`, so expect a container/network restart.
   Restart Matchbox after the commit: changing the Podman network definition
   alone left the running bridge on `/24` during the first rollout, which
   prevented the `/26` from being originated. Verify the kernel bridge address
   and exact route after restarting it. Matchbox keeps `.8`; host services gain their new addresses. TFTP and metrics retain old listeners
   during client migration. NTP binds only `.10`, with existing LAN/WireGuard
   interception and a scoped transit DNAT rule preserving the old device endpoint.
   Confirm the core learns `/26` and no longer learns the gateway's old `/24`.
   The full VyOS apply script resets configuration before rebuilding it: review
   its complete candidate diff against the running router, including unrelated
   repository drift, before committing it.
4. Reconcile the metrics scrape target and apply the retained Katl NTP settings
   through their normal workflows. Check successful metrics scrapes, NTP and PXE
   before retiring old listeners. DHCP leases advertise the new NTP and TFTP
   addresses on renewal; existing NTP interception redirects LAN requests.
5. Stop VyOS and cut over to NixOS using the gateway installation procedure.
   NixOS serves only the dedicated application endpoints. Verify uploads,
   provisioning, DHCP DNS transfers and every listener before marking the
   reserved DHCP DNS address active. Recheck the existing loopback assignments
   against the installed NixOS interfaces.
6. Retire the legacy container prefix/interface records after observing the
   resulting live configuration. Migrate other hosts incrementally when their
   service ownership is understood; no LAN, identity, transit or shared VIP
   renumbering is required for this policy.

If a NixOS DHCP DNS primary already has persistent zone data, update the
`primary.dhcp.cbannister.casa` A record to `.53` with authenticated `nsupdate`;
do not overwrite lease zones with seed files. Existing authoritative secondaries
also need their configured primary address updated before relying on transfers.

Rollback changes service listeners and consumers together. Keep device identity,
SSH access, VRRP and transit addressing available throughout. A rollback to
VyOS must stop NixOS first so there is only one owner of the gateway block.
