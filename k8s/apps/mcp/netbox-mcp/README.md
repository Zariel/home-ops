# NetBox MCP

[netbox-mcp](https://github.com/zariel/netbox-mcp) lets agents read and manage
NetBox at <https://netbox-mcp.cbannister.xyz/mcp> through the internal gateway.
Its write tools apply changes directly; approval of each tool call belongs to
the MCP client. It has no native Pocket ID OAuth integration; the shared
[MCP authentication components](../README.md) validate Pocket ID tokens and
require the `netbox:access` permission. The public OAuth client is
`netbox-mcp`, restricted to the `admin` group.

External Secrets imports `NETBOX_TOKEN` from the `netbox-mcp` 1Password item
into `netbox-mcp-secret` in the `mcp` namespace. The token is a v2 token for the
non-superuser NetBox user `netbox-mcp`, whose `netbox-mcp` object permission
grants every action on every object type except the identity and admin apps.
NetBox therefore bounds what the server can do and attributes its changes to
that user. Rotate the credential in NetBox and 1Password together. External Secrets refreshes it
hourly, and Reloader restarts the server when the Secret changes.

Envoy validates client tokens and removes the Authorization header before
forwarding requests. The backend network policy admits only the internal Envoy
gateway and node probes. The server connects to NetBox's cluster Service and
stores no persistent data.

Use the [client setup and validation procedure](../README.md) with hostname
`netbox-mcp.cbannister.xyz`, scope `netbox:access`, and client ID
`netbox-mcp`. Roll back by removing `netbox-mcp/ks.yaml` from the namespace
composition in Git and reconciling Flux; keep NetBox and its shared credential.
