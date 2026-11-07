# Jellystat

Jellystat uses its own database and role in `database/pg18vc`. The database is covered by CNPG backups. Its backup-file PVC uses the shared VolSync component.

The internal route at `https://jellystat.cbannister.xyz` requires Pocket ID's `admin` group. Jellystat has no native OIDC support, so Envoy handles OIDC. Set **Settings > Require Login** to **No** to open Jellystat after Pocket ID authentication without a second login. This application setting persists in PostgreSQL; it is not an environment override in the deployed version. Keep the gateway OIDC policy and ingress restrictions in place because Jellystat permits automatic login with this setting disabled.

On a fresh database, sign in as `admin` with the password from the `jellystat-admin` item in the `k8s` 1Password vault, complete setup, and disable **Require Login**. To restore the application password prompt, set **Require Login** to **Yes**.

ESO generators provision the `jellystat-db`, `jellystat-jwt`, and `jellystat-admin` vault items through `PushSecret` with `IfNotExists`. ExternalSecret imports those durable values once. Recreating the Kubernetes Secret restores the same values from 1Password. Rotation requires coordinating the vault values, database role, and application Secret; normal reconciliation does not rotate them.

Connect Jellyfin at `http://jellyfin.default.svc.cluster.local:8096` with a dedicated Jellyfin API key. Jellystat owns its connection settings in PostgreSQL. Its pod can reach Jellyfin through the application ingress policy.
