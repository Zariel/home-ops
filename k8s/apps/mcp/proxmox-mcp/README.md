# Proxmox VE MCP

[mcp-pve](https://github.com/samik081/mcp-pve) lets agents manage the Proxmox
VMs in the `agents` pool on `pve` at <https://proxmox-mcp.cbannister.xyz/mcp>
through the internal gateway. It has no caller authentication of its own; the
shared [MCP authentication components](../README.md) validate Pocket ID tokens
and require the `proxmox:access` permission, and the backend network policy
admits only the internal Envoy gateway and node probes. The public OAuth client
is `proxmox-mcp`, restricted to the `admin` group.

External Secrets imports `PVE_TOKEN_ID` and `PVE_TOKEN_SECRET` from the
`proxmox-mcp` 1Password item into `proxmox-mcp-secret`. The token is
`agent@pve!mcp`, a privilege-separated token whose effective permissions are
the intersection of its own ACLs and those of `agent@pve`; both carry the same
grants, so change them together:

| Path | Role |
| --- | --- |
| `/pool/agents` | `AgentVM` |
| `/storage/{vmdata,data,local-zfs,zfs-isos,pbs}` | `PVEDatastoreUser` |
| `/sdn/zones/localnetwork/vmbr1/{10,20}` | `PVESDNUser` |

`AgentVM` grants power, console, configuration (except hardware type and
passthrough), snapshot, rollback and backup on the pool's VMs, but not
`VM.Allocate`, so agents cannot create or destroy VMs. The bridge grants limit
NICs to the Servers and Trusted VLANs. Add a VM to agent management with
`pveum pool modify agents --vms <vmid>`; Proxmox, not the MCP server's tool
tier, is what bounds the agents.

Use the [client setup and validation procedure](../README.md) with hostname
`proxmox-mcp.cbannister.xyz`, scope `proxmox:access`, and client ID
`proxmox-mcp`. Roll back by removing `proxmox-mcp/ks.yaml` from the namespace
composition in Git and reconciling Flux; revoke the token with
`pveum user token remove agent@pve mcp`.
