# Speedtest Tracker

Speedtest Tracker measures cluster-to-internet download, upload, latency, and
packet loss using Ookla's CLI. The dashboard is at
<https://speedtest.cbannister.xyz>. Tests run at minute 17 every six hours in
Europe/London time, with results retained for 365 days. Administrators can run
additional tests from the dashboard. The result includes the Kubernetes node's
network path and any competing WAN traffic.

## Access

The route attaches only to the internal gateway. Envoy authenticates the existing
Pocket ID `admin` group; the Pocket ID operator owns the OIDC client Secret.
Sessions expire after 15 minutes without automatic refresh. The ingress policy
permits only the internal Envoy pods and the hosting node to reach the application.

Speedtest Tracker v1.15.1 has no native OIDC support. Gateway authentication controls
admission, while Speedtest Tracker retains its own local administrator accounts.
After signing in through Pocket ID, the results dashboard is available without an
additional application login. To run tests or change settings, use `/admin` and the
initial local administrator `admin@cbannister.xyz`. Retrieve its generated password
with:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl -n default get secret speedtest-tracker-secret \
  -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 --decode
```

Changing the password in the application does not update the bootstrap Secret.
The container uses these initial administrator settings only when creating the
database. There is no anonymous external route.

## Persistence and recovery

The shared VolSync component provides a 2 GiB Ceph PVC and backs up `/config`,
including the SQLite database, to the NAS. External Secrets generates `APP_KEY`
and the bootstrap administrator password once, using the shared `password32`
generator. It retains the generated Secret across ExternalSecret deletion and
application reinstalls; neither deployments nor refreshes rotate its values.

Preserve `speedtest-tracker-secret` with the database during recovery. Restore the
original `APP_KEY` before starting against an existing database; a new key cannot
decrypt application data encrypted with the old key. Reverting the application
commit removes the workload and its GitOps-owned storage resources, so preserve
the PVC or a current backup before uninstalling. Revert only the image change for
an application rollback, accounting for any database migrations in the release.

Upstream documentation: [Speedtest Tracker](https://docs.speedtest-tracker.dev/)
and [LinuxServer container](https://docs.linuxserver.io/images/docker-speedtest-tracker/).
