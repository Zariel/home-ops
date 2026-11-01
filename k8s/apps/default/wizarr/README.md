# Wizarr

Wizarr manages invitations at `https://join.cbannister.xyz`. Pocket ID authenticates administrators through Envoy Gateway; invitation recipients create local media-server accounts.

## Administrator access

The `wizarr-oidc` Flux Kustomization registers the Pocket ID client and waits for it to become ready. Only members of the existing `admin` group may authorize this client. The Pocket ID operator owns the generated `wizarr-oidc` Secret, including Envoy's `client-secret` key. No client secret belongs in plaintext manifests.

The `wizarr` SecurityPolicy protects the default HTTPRoute, including `/login`, `/setup/`, `/settings`, `/api`, and administrator wizard previews. It uses the authorization-code flow with PKCE. Tokens last 15 minutes and are not refreshed automatically, so access is checked again through Pocket ID after expiry. Removing group membership does not immediately invalidate an already-issued gateway session.

Wizarr's proxy SSO uses its built-in administrator identity. Pocket ID groups control admission to administration; they are not synchronized into Wizarr or Jellyfin. Use `/logout` to clear the gateway session. Your Pocket ID browser session is separate.

The ingress policy allows only the external Envoy pods and hosting node to reach TCP `5690`. Keep that restriction in place when `DISABLE_BUILTIN_AUTH` is enabled: Wizarr trusts requests that reach its login endpoint. A Kubernetes port-forward bypasses gateway authentication and is reserved for operators with cluster access.

## Invite viewers

Sign in at the public hostname, then add Jellyfin in Settings:

| Field | Value |
|---|---|
| Server type | Jellyfin |
| Internal URL | `http://jellyfin.default.svc.cluster.local:8096` |
| External URL | `https://jellyfin.cbannister.xyz` |
| API key | A dedicated key created in Jellyfin's administrator dashboard |

Scan and select the required libraries. Keep downloads and Live TV disabled unless needed, and hide new users from login screens. Create a single-use invitation with a short link expiry. Set a membership duration only when viewer access should also expire.

The `wizarr-invitations` HTTPRoute permits invitation-code pages, invitation processing, password-reset links, guest wizard pages, artwork, and static assets without Pocket ID authentication. Administrator setup and wizard previews are intentionally excluded. Review the allowlist against Wizarr's routes when upgrading the application.

## Verify or recover access

Run the read-only public-access checks with Python 3:

```sh
python3 k8s/apps/default/wizarr/tests/access.py
```

The checks verify administrator redirects, PKCE, guest pages, path normalization, and rejection of forged authentication headers and callbacks. Complete a real Pocket ID login and a single-use test invitation to check the browser and account-creation flows.

If Pocket ID is unavailable, an operator can reach the existing Wizarr administrator session through a local port-forward:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl --namespace default port-forward deployment/wizarr 5690:5690 --address=127.0.0.1
```

Open `http://127.0.0.1:5690/login` only on the forwarding machine. To return to built-in authentication, remove `DISABLE_BUILTIN_AUTH` through GitOps before removing the gateway or network protections. Keep the existing persistent configuration volume; it contains Wizarr's local accounts, media-server connections, and invitations.
