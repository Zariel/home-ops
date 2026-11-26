# Flare

[Flare](https://flare.cbannister.xyz) is served through the internal HTTPS
gateway. Sign in with Pocket ID using the `admin` group. Local self-registration
is closed. A link to a shareable upload or paste works for signed-out visitors
on the internal network. Flare's **Private** visibility limits access to the
owner and accounts with content moderation permissions.

Automatic OCR is disabled because its language data requires an external
download. File previews, uploads, and pastes use local storage.

The Pocket ID operator owns the `flare-oidc` Secret. Flare stores native OIDC
configuration in PostgreSQL. After client credential rotation, update
**Settings → Access** with the new client secret. Use `https://id.cbannister.xyz`
as the issuer, `flare` as the client ID, and
`https://flare.cbannister.xyz/api/auth/callback/oidc` as the callback.

The local recovery administrator signs in at `/auth/login?local=1` with
`flare-admin@example.invalid` and the password in the `flare-recovery` item
in the `k8s` 1Password vault. Keep that item in sync if the recovery password
changes. If reinitializing against an empty database, complete first-run setup
over a loopback port-forward before attaching the gateway route.

CloudNativePG owns the `flare` database and role on `database/pg18vc`. The
database is backed up with the cluster and retained on removal. VolSync backs
up the upload volume. External Secrets saves the generated database password
and session key in the `flare-db` and `flare-session` 1Password items. Keep the
session key with database backups, since Flare uses it for both sessions and
encrypted application settings. Coordinate `flare-db` changes across the
database and application ExternalSecrets before restarting Flare.
