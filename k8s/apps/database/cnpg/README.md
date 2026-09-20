# PostgreSQL operations

`database/pg18vc` has three instances with local storage, one per node.
Pod readiness alone does not establish that replication works.

## Before node maintenance

Run `kubectl cnpg status pg18vc -n database` with the repository kubeconfig.
Require both replicas to be streaming, caught up, and healthy, with WAL
archiving working and a recent successful Barman backup. Identify the primary
before draining; use CNPG's supported switchover when maintaining its node.
Respect disruption budgets and maintain only one node at a time. Wait for all
three instances and replication to recover before proceeding to another node.
Check Ceph health and the target node's OSD/monitor stop safety separately.

## Restoring

Choose the recovery source explicitly. `bootstrap.recovery` is only used for
initial creation; the source currently recorded in `cluster.yaml` is the source
of the September 2026 restore, not the newest backup destination.

Every newly restored cluster must archive to a fresh, unused `serverName`.
Never enable `cnpg.io/skipEmptyWalArchiveCheck` to reuse an existing archive.
Keep the destination stable through routine node upgrades and failovers.
Preserve the source archive and isolate restore rehearsals from application
traffic and production archive writes.

After restoring, verify actual streaming on both replicas, take a fresh backup,
and verify its required WAL is archived to the same destination. Periodically
test a full restore; a completed Backup resource alone is not a restore test.

## Emergency configuration changes

Publish persistent fixes through GitOps. If an approved temporary Flux hold is
needed during recovery, keep it until the source artifact contains the fix.
Then remove `kustomize.toolkit.fluxcd.io/reconcile` from the Cluster, reconcile
the `database/pg18vc` Kustomization, and recheck the live archive destination.

The September 2026 recovery uses archive `pg18vc-v4-20260920`. Its fresh backup
is `pg18vc-recovery-stable-20260920` (Barman ID `20260920T154929`). Do not rely on
the earlier `pg18vc-recovery-20260920` backup: its WAL was split across archive
destinations during reconciliation.

## Alert validation

Run `bash k8s/apps/database/cnpg/tests/check.sh` with `yq` and `promtool` on
PATH. The tests cover healthy operation, disconnected replicas despite
available metrics, missing metrics, and a backup exceeding the daily window.
