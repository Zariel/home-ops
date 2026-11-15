# Home Assistant MCP

Home Assistant MCP runs in the `mcp` namespace at
<https://home-assistant-mcp.cbannister.xyz/mcp>. Its upstream Home Assistant
instance remains in `default`, reached at
`http://home-assistant.default.svc.cluster.local:8123`.

This is a trusted internal machine endpoint without client OAuth. It preserves
the `ha-mcp-web` access model: clients share the Home Assistant account whose
token External Secrets imports from the `home-assistant-mcp` 1Password item.
The internal ListenerSet provides TLS, and the backend network policy admits
only the internal Envoy gateway and node probes. Public exposure requires an
authentication integration; the shared MCP OAuth component is not attached to
this endpoint. Gaming's Codex configuration uses the existing endpoint URL.

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
