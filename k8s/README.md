# Kubernetes conventions

These policies govern manifest changes. Existing deviations are migration work, not templates for new applications. Keep migrations scoped to the requested work.

## Manifest organization

| Path | Responsibility |
| --- | --- |
| `bootstrap/` | Resources needed to establish the cluster and Flux |
| `flux/` | Root reconciliation and cluster configuration |
| `apps/<namespace>/kustomization.yaml` | Namespace composition and application registration |
| `apps/<namespace>/<application>/ks.yaml` | Flux Kustomizations for application reconciliation units |
| `apps/<namespace>/<application>/<unit>/` | Renderable Kustomize unit and its resources |
| `components/` | Reusable Kustomize components |

Use `app/` for a single application unit. Split into descriptive units such as `operator/`, `cluster/`, `oidc/`, or `instance/` when ownership or readiness ordering requires it. Use existing namespaces where appropriate; new namespaces need an ownership or isolation reason. Do not introduce a parallel environment or chart-type hierarchy.

Register application `ks.yaml` files in the namespace Kustomization. Keep HelmRelease and OCIRepository resources, secrets, routes, policies, monitors, and application-specific alert rules with their application. Keep mounted configuration in `config/` and supporting assets in descriptive subdirectories. Shared controllers have their own application directories; shared namespace resources can use a namespace's `common/` application.

Distinguish Flux Kustomizations in `ks.yaml` from Kustomize build files named `kustomization.yaml`. Set Flux paths and target namespaces explicitly. Inspect inherited defaults in `flux/apps.yaml` before duplicating policy. Add `dependsOn` only for real readiness prerequisites. Give each resource one reconciliation owner.

Use the common namespace component and existing VolSync components where applicable. Preserve resource names and paths unless migration is required: pruning and ownership changes can delete resources or interrupt workloads.

## Secrets

External Secrets Operator (ESO) is the default for both importing and generating application secrets.

- Import externally issued credentials through the `onepassword` ClusterSecretStore. Commit references and templates, not values.
- Generate passwords and random keys with ESO generators where needed. Do not manually generate and encrypt them as the normal provisioning workflow. See `apps/default/common/app/generators.yaml` and `apps/default/immich/app/externalsecret.yaml` for existing examples.
- Materialize Secrets in their consumers' namespaces. Sharing a generator definition does not establish a shared credential; consumers requiring the same value need one authoritative source.
- Define refresh, deletion, recovery, and rotation behavior. Reconciliation must not silently replace credentials tied to persisted application state. Coordinate rotation across consumers and preserve recovery-critical values beyond an ephemeral Secret where necessary.
- Use PushSecret when generated or controller-issued values need export to an external store. Define ownership and avoid competing pull/push writers. Certificate export under `apps/network/certificates/export/` is an existing example.

SOPS is appropriate for credentials needed before ESO and its store are available, including Flux bootstrap and 1Password Connect credentials. Node management secrets have an independent bootstrap lifecycle. Encrypted files must match `.sops.yaml`. Never commit plaintext secrets or print secret values during verification.

Dedicated controllers can own secrets intrinsic to their lifecycle, such as cert-manager certificates and Pocket ID operator client credentials. Do not add a competing ESO owner. Document other special cases beside the application: why ESO cannot own the value, who does, and how recovery and rotation work. Existing application SOPS files are not blanket exceptions; preserve their values during later migration.

## Network trust and identity

Internal network access is trusted. External ingress is untrusted, including requests arriving through Cloudflare. Internal tools do not need authentication solely because they expose a web UI. This does not justify public access to internal administration or trusting external identity headers.

Choose internal or external exposure explicitly. Follow the Envoy Gateway and ListenerSet configuration in `apps/network/envoy-gateway/gateways/`. Trace route parent references to the gateway: DNS and hostnames alone do not establish the security boundary. Cloudflared forwards the wildcard domain to the external gateway.

Apps requiring accounts must use Pocket ID where supported, including internal apps. Prefer native OIDC so accounts and permissions retain their application meaning. Declare clients through the Pocket ID operator and let it own client credentials; Grafana's `oidc/` unit is an example. Use gateway OIDC when native integration is unsuitable or when it improves security. Gateway admission does not automatically provide application accounts or authorization.

Separate intentionally anonymous features from private and administrative routes on public applications. Protect private routes with application authentication or gateway policy as appropriate. Restrict callback URLs and allowed groups. Verify anonymous access, allowed and denied users, session/logout behavior, APIs, and webhooks. Check alternate routes and forged identity headers for bypasses.

Document unsupported identity integrations and deliberate anonymous routes beside the application. Wizarr's README illustrates administrator authentication alongside public invitations. Machine accounts and applications without suitable identity support need explicit treatment rather than an assumed OIDC integration.

## Validation

Render changed units and namespace composition with `kubectl kustomize <path>`. Check ownership, namespaces, secret references, route parents, and required CRDs. The root `apps/` path relies on Flux composition and does not contain a standalone Kustomize build file.

Use server-side dry runs where cluster schemas or admission matter. Rendering does not establish secret readiness or application behavior. After an authorized rollout, verify actual behavior and relevant metrics, logs, and alerts. Report when live verification was not performed.
