# Home Assistant MCP

Home Assistant MCP runs in the `mcp` namespace at
<https://home-assistant-mcp.cbannister.xyz/mcp>. Its upstream Home Assistant
instance remains in `default`, reached at
`http://home-assistant.default.svc.cluster.local:8123`.

The shared [MCP authentication components](../README.md) require Pocket ID
access tokens with the `home-assistant:access` permission and the endpoint URL
as their audience. The public OAuth client is `home-assistant-mcp`,
restricted to the `admin` group. Envoy validates client tokens and removes the
Authorization header before forwarding requests to `ha-mcp-web`.

Clients share the Home Assistant account whose token External Secrets imports
from the `home-assistant-mcp` 1Password item. Pocket ID controls admission to
MCP; the Home Assistant account controls application permissions. The internal
ListenerSet provides TLS, and the backend network policy admits only the
internal Envoy gateway and node probes.

Use the [agent setup procedure](../README.md) with scope
`home-assistant:access`, client ID `home-assistant-mcp`, and the existing
endpoint URL. After activating gaming's agent configuration, sign in to the
`home-assistant` server from each agent.

The `home-assistant-mcp` PVC holds server settings, tool policy, and usage
history. VolSync backs it up to the `home-assistant-mcp` Restic repository and
restores that repository when provisioning a replacement PVC. The application
name and backup repository stay the same across namespace changes.

For a namespace move, stop the source deployment through Git and Flux, then
trigger and verify a final VolSync backup before moving the manifests. Keep
the source namespace's Helm release stopped until it is removed. Verify the
destination's restore, file checksums, and Home Assistant tool access before
considering the migration complete. Roll back through Git and Flux using the
same backup repository; avoid running writers in both namespaces.
