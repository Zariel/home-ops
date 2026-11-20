# MCP services

The `mcp` namespace groups MCP servers and their application credentials, routes,
identity registrations, and authentication policies. Each server owns a single
`app/` reconciliation unit. Shared identity and gateway controllers remain in
their existing namespaces.

## Shared authentication component

The reusable configuration lives in `k8s/components/mcp-auth`. Add
`../../../../components/mcp-auth` to the server's Flux Kustomization through
`spec.components`, relative to the unit's `spec.path`, and supply the following
values through `spec.postBuild.substitute`:

| Variable | Meaning |
| --- | --- |
| `APP` | Service, HTTPRoute, and workload name, prefix for the generated resources, and endpoint host `${APP}.cbannister.xyz` |
| `MCP_SCOPE` | The server's dedicated API permission, such as `example:access` |
| `MCP_DISPLAY_NAME` | Human-readable service name |

For example:

```yaml
spec:
  components:
    - ../../../../components/mcp-auth
  dependsOn:
    - name: envoy-gateway-operator
      namespace: network
    - name: pocket-id-instance
      namespace: default
  postBuild:
    substitute:
      APP: example-mcp
      MCP_SCOPE: example:access
      MCP_DISPLAY_NAME: Example MCP
```

Server manifests can use `${APP}.cbannister.xyz` wherever they need the endpoint
host, such as allowed-host settings.

The component generates:

- a PocketIDAPI and a public agent client, both named `${APP}`;
- the JWT and scope SecurityPolicy, OAuth discovery route, and 401 challenge;
- the authenticated `${APP}` HTTPRoute, which serves only `/mcp` from port 80
  of the `${APP}` Service and removes Authorization and Grafana credential
  headers before forwarding;
- the `${APP}-gateway` CiliumNetworkPolicy, which admits ingress to the `http`
  container port only from the internal Envoy gateway and the node.

Keeping the route beside the policies that target it by name prevents a renamed
route from losing authentication, and the ingress policy stops other workloads
from bypassing token validation. The public clients have no secret, so the
application does not wait on its identity registration and one unit owns both.
No shared controller or reconciliation unit owns application policies.

These resources serve `/mcp` through the internal `internal-cbannister-xyz`
ListenerSet, use Pocket ID's `admin` group, issue 15-minute access tokens, and
register the agents' loopback callbacks on port 4321.

Each application names its MCP container port `http` and exposes it as Service
port 80 targeting `http`; the route and ingress policy rely on both. The
application owns its egress policy and must not declare its own route.

A ListenerSet-level policy would apply the same static audiences and permissions
to every attached route. The component shares the configuration while preserving
a separate audience, scope, and public discovery document for each server. It
is opt-in per server; other routes on the internal gateway are unaffected.

## Authentication and network access

Prefer native MCP OAuth support when a server provides it. Otherwise, use Envoy
Gateway's JWT SecurityPolicy with Pocket ID as the authorization server. A browser
OIDC redirect policy alone does not provide MCP bearer-token authentication.

The shared components implement the following for each server:

- Register a PocketIDAPI with the canonical MCP endpoint as its resource and a
  dedicated access permission. Require that resource as the JWT audience and
  that permission as the scope in the SecurityPolicy, along with Pocket ID's
  issuer and signing keys. Extract tokens only from the Authorization header.
- Register a public PocketIDOIDCClient for the agents with PKCE, exact loopback
  callbacks, and access restricted to the `admin` group. Grant user-delegated
  access to the API permission. The Pocket ID operator owns these resources;
  public clients need no client secret.
- Serve anonymous OAuth protected-resource metadata at
  `/.well-known/oauth-protected-resource/mcp` and
  `/.well-known/oauth-protected-resource` for an endpoint at `/mcp`. Return a
  `WWW-Authenticate` discovery challenge with authentication failures. Its
  `scope` must include `offline_access`, because clients request the
  challenge's scopes in preference to `scopes_supported`. Keep the
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

## Agent configuration and login

Each server has one public client, `${APP}`, shared by the coding agents. It
accepts the loopback callbacks `http://127.0.0.1:4321/callback`, used by Codex,
and `http://localhost:4321/callback`, used by Claude Code. Separate clients per
agent would only separate revocation and audit; public clients have no secret.

Agent configuration is generated from a single server list in nix-ops
(`systems/gaming/mcp-servers.nix`), which maps each server to Codex's
`config.toml` and Claude Code's MCP configuration. Both request the scopes
`openid`, `${MCP_SCOPE}`, and `offline_access`, use the client ID `${APP}`, and
listen on port 4321. The callback and fixed listener port must match the Pocket
ID client. Pocket ID advertises issuer-bound authorization responses, allowing
agents to reuse the exact callback. Let the agent obtain the OAuth resource from
the gateway's discovery document; setting Codex's `oauth_resource` as well can
duplicate the resource parameter and cause Pocket ID to reject the request. See
the [Codex OAuth configuration](https://learn.chatgpt.com/docs/extend/mcp),
[Claude Code MCP authentication](https://code.claude.com/docs/en/mcp), and
[Pocket ID API access](https://pocket-id.org/docs/guides/apis).

After Flux has reconciled the server, sign in from the agent: run
`codex mcp login <name>` for Codex, or select the server under `/mcp` in Claude
Code, then complete Pocket ID sign-in. `codex mcp logout <name>` and Claude
Code's `/mcp` menu remove locally stored credentials. The name is the server's
key in the generated configuration.

The agents store and refresh tokens. Access-token lifetimes are configured per
Pocket ID client; an expired access token should be renewed without another
interactive login. Pocket ID defaults to 30 days of inactivity for refresh
tokens, with the lifetime restarting at each refresh. See [token lifetimes](https://pocket-id.org/docs/guides/scopes-and-claims).
Revocation, expired refresh tokens, lost local credentials, or a recreated
client require login again. An already-issued access token remains valid until
expiry because Envoy validates it locally.

## Validation and rollout

Render changed `app/` units and the namespace composition. Use
`flux build kustomization` with `--dry-run --strict-substitute`, the local
`--kustomization-file`, the unit's `--path`, and `--namespace mcp` to include the
components and resolve their inputs. A plain `kubectl kustomize` of an app unit
does not include components attached by its Flux Kustomization. Check that
workloads, credentials, policies, and identity resources render into `mcp`, while
references to shared controllers keep their original namespaces. Use server-side
dry runs where the target namespace exists. App reconciliation must depend on
Pocket ID and Envoy Gateway where their readiness is required.

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
