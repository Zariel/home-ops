# NetBox MCP

The [NetBox Labs MCP server](https://github.com/netboxlabs/netbox-mcp-server)
provides read-only NetBox tools at <https://netbox-mcp.cbannister.xyz/mcp> through
the internal gateway. It has no native Pocket ID OAuth integration; the shared
[MCP authentication components](../README.md) validate Pocket ID tokens and
require the `netbox:access` permission. The public OAuth client is
`netbox-mcp`, restricted to the `admin` group.

External Secrets imports `NETBOX_API_TOKEN` from the existing `netbox` 1Password
item into `netbox-mcp-secret` in the `mcp` namespace. NetBox remains the authority
for that token's permissions; the MCP server exposes no mutation tools. Rotate
the credential in NetBox and 1Password together. External Secrets refreshes it
hourly, and Reloader restarts the server when the Secret changes.

Envoy validates client tokens and removes the Authorization header before
forwarding requests. The backend network policy admits only the internal Envoy
gateway and node probes. The server connects to NetBox's cluster Service and
stores no persistent data.

Use the [client setup and validation procedure](../README.md) with hostname
`netbox-mcp.cbannister.xyz`, scope `netbox:access`, and client ID
`netbox-mcp`. Roll back by removing `netbox-mcp/ks.yaml` from the namespace
composition in Git and reconciling Flux; keep NetBox and its shared credential.
