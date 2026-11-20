# MCP services

The `mcp` namespace groups MCP servers and their application credentials, routes,
and authentication policies. Each server owns its `app/` reconciliation unit and,
when needed, an `oidc/` unit for Pocket ID resources. Shared identity and gateway
controllers remain in their existing namespaces.

## Shared authentication components

The reusable configuration lives in `k8s/components/mcp-auth`:

| Component | Added to | Resources |
| --- | --- | --- |
| `../../../../components/mcp-auth` | The server's app Flux Kustomization | JWT and scope policies, OAuth discovery and challenges |
| `../../../../components/mcp-auth/oidc` | The server's identity Flux Kustomization | Pocket ID API and public Codex client |

Attach each through `spec.components`, relative to the unit's `spec.path`. Supply
the following values through `spec.postBuild.substitute` on both Kustomizations:

| Variable | Meaning |
| --- | --- |
| `APP` | Protected HTTPRoute name and prefix for the generated resources |
| `MCP_HOST` | Endpoint hostname without scheme or path |
| `MCP_SCOPE` | The server's dedicated API permission, such as `example:access` |
| `MCP_DISPLAY_NAME` | Human-readable service name |

For example, the app Flux Kustomization contains:

```yaml
spec:
  components:
    - ../../../../components/mcp-auth
  postBuild:
    substitute:
      APP: example-mcp
      MCP_HOST: example-mcp.cbannister.xyz
      MCP_SCOPE: example:access
      MCP_DISPLAY_NAME: Example MCP
```

Use the `mcp-auth/oidc` component with the same identity values in the identity
unit. The generated API is named `${APP}` and the Codex client `${APP}-codex`.
The app depends on that identity unit and Envoy Gateway; the identity unit depends
on `pocket-id-instance` in `default`. Each server's Flux units own their generated
resources. No shared controller or reconciliation unit owns application policies.

These components serve `/mcp` through the internal `internal-cbannister-xyz`
ListenerSet, use Pocket ID's `admin` group, issue 15-minute access tokens, and
register the Codex loopback callback at `http://127.0.0.1:4321/callback`.
The app component also owns the authenticated `${APP}` HTTPRoute, which serves
only `/mcp` from port 80 of the `${APP}` Service and removes Authorization and
Grafana credential headers before forwarding. Keeping the route beside the
policies that target it by name prevents a renamed route from losing
authentication. The component's `${APP}-gateway` CiliumNetworkPolicy admits
ingress to the `http` container port only from the internal Envoy gateway and
the node, so other workloads cannot bypass token validation.

Each application names its MCP container port `http` and exposes it as Service
port 80 targeting `http`; the route and ingress policy rely on both. The
application owns its egress policy and must not declare its own route.

A ListenerSet-level policy would apply the same static audiences and permissions
to every attached route. Components share the configuration while preserving a
separate audience, scope, and public discovery document for each server. They
are opt-in per server; other routes on the internal gateway are unaffected.

## Authentication and network access

Prefer native MCP OAuth support when a server provides it. Otherwise, use Envoy
Gateway's JWT SecurityPolicy with Pocket ID as the authorization server. A browser
OIDC redirect policy alone does not provide MCP bearer-token authentication.

The shared components implement the following for each server:

- Register a PocketIDAPI with the canonical MCP endpoint as its resource and a
  dedicated access permission. Require that resource as the JWT audience and
  that permission as the scope in the SecurityPolicy, along with Pocket ID's
  issuer and signing keys. Extract tokens only from the Authorization header.
- Register a public PocketIDOIDCClient for Codex with PKCE, an exact loopback
  callback, and access restricted to the `admin` group. Grant user-delegated
  access to the API permission. The Pocket ID operator owns these resources;
  public clients need no client secret.
- Serve anonymous OAuth protected-resource metadata at
  `/.well-known/oauth-protected-resource/mcp` and
  `/.well-known/oauth-protected-resource` for an endpoint at `/mcp`. Return a
  `WWW-Authenticate` discovery challenge with authentication failures. Keep the
  metadata route separate from the authenticated application route.
- Choose the route's gateway explicitly. An internal ListenerSet keeps the
  endpoint internal; public exposure requires a deliberate external route.
  Merge per-route BackendTrafficPolicies with gateway defaults so streaming
  timeouts and connection settings are preserved.

Keep upstream application credentials under External Secrets ownership in the
server's namespace. Gateway authentication admits clients to MCP; the upstream
service account still determines which application operations are permitted.
Keep a Cilium egress policy with each workload; the shared component restricts
ingress to the internal Envoy gateway and the node for probes.
Keep server-side mutation confirmation enabled where supported. Human approval
belongs to the MCP client.

## Codex configuration and login

Use the endpoint, API permission, client ID, and callback declared by the server's
manifests in `~/.codex/config.toml`. For example, replacing the placeholders:

```toml
[mcp_servers.example]
url = "https://<server-host>/mcp"
scopes = ["openid", "<server-access-scope>", "offline_access"]

[mcp_servers.example.oauth]
client_id = "<server-codex-client-id>"
callback_url = "http://127.0.0.1:4321/callback"
callback_port = 4321
```

The callback and fixed listener port must match the Pocket ID client. Pocket ID
advertises issuer-bound authorization responses, allowing Codex to reuse the
exact callback. Let Codex obtain the OAuth resource from the gateway's discovery
document; do not also set `oauth_resource`, which can duplicate the resource
parameter and cause Pocket ID to reject the request. See the [Codex OAuth configuration](https://learn.chatgpt.com/docs/extend/mcp)
and [Pocket ID API access](https://pocket-id.org/docs/guides/apis).

After Flux has reconciled the server and its identity resources, run
`codex mcp login <name>`, complete Pocket ID sign-in, and reconnect the MCP server.
Use `codex mcp logout <name>` to remove locally stored credentials. The name is
the key under `mcp_servers` in the local configuration.

Codex stores and refreshes tokens. Access-token lifetimes are configured per
Pocket ID client; an expired access token should be renewed without another
interactive login. Pocket ID defaults to 30 days of inactivity for refresh
tokens, with the lifetime restarting at each refresh. See [token lifetimes](https://pocket-id.org/docs/guides/scopes-and-claims).
Revocation, expired refresh tokens, or lost local credentials require login
again. An already-issued access token remains valid until expiry because Envoy
validates it locally.

## Validation and rollout

Render changed `app/` and `oidc/` units and the namespace composition. Use
`flux build kustomization` with `--dry-run --strict-substitute`, the local
`--kustomization-file`, the unit's `--path`, and `--namespace mcp` to include the
components and resolve their inputs. A plain `kubectl kustomize` of an app unit
does not include components attached by its Flux Kustomization. Check that
workloads, credentials, policies, and identity resources render into `mcp`, while
references to shared controllers keep their original namespaces. Use server-side
dry runs where the target namespace exists. App reconciliation must depend on
its identity unit and Envoy Gateway where their readiness is required.

After rollout, verify anonymous discovery, `401` discovery challenges for missing
or invalid tokens, rejection of wrong-audience tokens, and `403` responses for
missing API permissions. Check allowed and denied users, token refresh, tool
discovery, and denial of direct backend access from other workloads. Verify
mutation previews without confirming real application changes.

Namespace moves recreate namespace-scoped resources and Helm releases. Coordinate
the old release's removal and the new release's readiness through Flux; a move
can interrupt MCP connections. Persistent data needs an explicit migration plan.
Roll back through Git and Flux, keeping authentication and network policies
together with their workloads.
