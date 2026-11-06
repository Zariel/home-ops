# NetBox authentication

NetBox at <https://netbox.cbannister.xyz> uses native Pocket ID OIDC with PKCE. The route remains internal. Only Pocket ID members of `admin` may authorize the client. NetBox manages application permissions; newly created OIDC accounts receive no permissions by default. Pocket ID group membership is not synchronized into NetBox permissions.

The `netbox-oidc` Flux Kustomization waits for the Pocket ID client before NetBox consumes its credentials. The Pocket ID operator exclusively owns the `netbox-oidc` Secret. NetBox reads the mounted credentials at startup; Reloader restarts it when the Secret or configuration changes. The worker and housekeeping workloads are disabled; if enabled, give them the same OIDC configuration and credential mounts.

The existing local `cbannister` superuser is linked to Pocket ID subject `664ef3d2-dc3c-429f-bfad-dc880647fb8a` through NetBox's `social_django.models.UserSocialAuth` table (`provider=oidc`). This association is application database state and is retained by database backups. Email addresses differ between the accounts, so automatic email or username matching is deliberately not configured. If restoring a database predating the migration, verify the Pocket ID subject and associate it with the existing user before their first OIDC login; do not create a duplicate account or grant every admitted user superuser access.

Local username/password login remains available at `/login/` for recovery. NetBox logout clears the application session; the Pocket ID browser session remains separate. Removing group membership prevents subsequent OIDC authorization, but does not revoke an existing NetBox session. API tokens continue to authenticate directly to NetBox without browser OIDC.

To roll back, disable `remoteAuth.enabled` and remove the OIDC configuration and credential mounts in Git, then reconcile Flux. Preserve the database, local administrator credentials, API token peppers, and OIDC account association. Do not delete the operator-owned client Secret to rotate credentials; coordinate rotation through the Pocket ID operator and confirm NetBox restarts with the updated Secret.
