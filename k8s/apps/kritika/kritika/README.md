# Kritika

The dashboard at <https://kritika.cbannister.xyz> uses Pocket ID with the
`admin` group. The public hostname only accepts GitHub's signed
`POST /hooks/github` deliveries. The private GitHub App is
[Kritika for Zariel](https://github.com/apps/kritika-for-zariel).
Install it on selected repositories and enable each repository in Kritika.
Reviews send pull request and repository context to OpenAI.

External Secrets reads `OPENAI_API_KEY` from `kritika` and the GitHub App
credentials from `kritika-github` in the `k8s` 1Password vault. Rotate the
OpenAI key and GitHub credentials there. Reloader restarts Kritika after
the Secret updates.

CloudNativePG owns the `kritika` database and its two login roles on
`database/pg18vc`. The database is covered by the cluster's backups and
retained on removal. External Secrets generates the two role passwords
and persists them in the `kritika-owner` and `kritika-app` vault items
with `IfNotExists`. To rotate a password, update the vault item and
refresh its CreatedOnce ExternalSecrets in both namespaces together.
