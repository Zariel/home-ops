# Observability operations

Use metrics, logs, alerts, and Kubernetes state together when investigating a failure. Start with read-only access. Do not change dashboards, silence alerts, or modify notification routing as part of diagnosis unless the task authorizes those changes.

## Access

Grafana is available at <https://grafana.cbannister.xyz>. Its configuration permits anonymous Viewer access; Pocket ID provides administrator login. Discover available Grafana connector tools when present and use their read-only queries. Otherwise use Grafana Explore or its read APIs with existing authorized access. Do not extract administrator secrets just to read telemetry.

The configured data sources are defined in `apps/monitoring/grafana/app/grafanadatasource.yaml`:

| Data source | UID | Query purpose |
| --- | --- | --- |
| VictoriaMetrics | `victoriametrics` | Prometheus-compatible metrics queries |
| VictoriaLogs | `victorialogs` | LogsQL log queries |
| Alertmanager | `alertmanager` | Alertmanager alert state |

Select the correct data source explicitly. Discover actual metric names and log fields before building queries; do not assume Loki syntax or label names for VictoriaLogs. Bound the time window and filter by the relevant namespace, workload, or node. Record the query and time range with findings. Missing telemetry is not proof of health.

Alertmanager also has an internal route at <https://alertmanager.cbannister.xyz>. For a local read-only API query, use a loopback port-forward in one terminal:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl -n monitoring port-forward service/alertmanager-ha 9093:9093 --address=127.0.0.1
```

Read alerts from another terminal, then stop the port-forward when finished:

```sh
curl --fail --silent --show-error http://127.0.0.1:9093/api/v2/alerts
```

These commands run from the repository root. For other direct Kubernetes commands, also set the repository kubeconfig; task wrappers set it automatically. If an endpoint is unavailable, inspect Services, endpoints, pods, and route conditions before assuming credentials are required. Keep query results free of secret values and unnecessary personal data.

## Network policy

Cilium enforces network policy, and Hubble records flows with their policy verdicts. For read-only flow queries, port-forward the relay and run the CLI from nixpkgs:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl -n kube-system port-forward service/hubble-relay 4245:80 --address=127.0.0.1
nix shell nixpkgs#hubble -c hubble observe --server 127.0.0.1:4245 --pod default/<app> --verdict DROPPED --since 10m
```

A `Policy denied` drop identifies a missing allow rule or an unexpected client. The relay retains only a few minutes of flows, and established connections may produce no new flows during a capture. An empty or short capture therefore does not establish which clients use a workload. Confirm consumers from application configuration or logs before restricting ingress.

Every policy drop is also logged. The Cilium agents export `POLICY_DENIED` and `POLICY_DENY` flows to stdout, aggregated every 30 seconds by pod, address, destination port, direction and reason, and Vector ships them to VictoriaLogs. Query them in Grafana's Explore with the VictoriaLogs datasource, for example `message_json.flow.verdict:DROPPED message_json.flow.source.pod_name:home-assistant*`. The fields are under `message_json.flow`, with the number of collapsed flows in `aggregate.ingress_flow_count` or `aggregate.egress_flow_count`. Unlike the relay, this history lasts as long as the logs.

`CiliumUnexpectedDrop` fires within five minutes of any `POLICY_DENIED` drop other than ICMP errors and internet scans of qBittorrent's torrent port. Use the logged flow to decide between an allow rule and an explicit `egressDeny` or `ingressDeny`, which reports `POLICY_DENY` and does not alert. `CiliumPolicyDenied` fires on drops that continue for most of an hour.

### Breakglass

When a policy blocks traffic that must flow now, label the namespace, or a single pod, with `cbannister.xyz/breakglass=true`. The `breakglass` clusterwide policy then admits all of its ingress and egress. Explicit deny rules still apply. Labelling needs only the API server, so it works when Flux cannot reconcile the fix:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl label namespace <namespace> cbannister.xyz/breakglass=true
# After the policy fix is reconciled from Git:
KUBECONFIG="$PWD/kubeconfig" kubectl label namespace <namespace> cbannister.xyz/breakglass-
```

Breakglass is an operator action outside GitOps; remove the label as soon as the fix is in Git, and confirm with `kubectl get ns,pods -A -l cbannister.xyz/breakglass` that nothing still carries it.

To see what a policy selected, run `cilium-dbg policy selectors` in the Cilium agent pod on the endpoint's node; `cilium-dbg bpf policy get <endpoint-id>` shows the realized allow entries. A valid policy status does not prove enforcement. After rollout, connect from the restricted pod to an allowed destination and to a trusted address that should be blocked, and from an unlisted pod that has no egress policy of its own.

## Incident workflow

1. Establish the symptom and time window. Inspect Flux reconciliation, workload readiness, events, and recent configuration changes.
2. Inspect Alertmanager alerts, including labels, timestamps, annotations, and suppression state. Distinguish firing alerts from pending rule evaluations and from successful notification delivery.
3. Correlate metrics and logs over the same interval. Use Kubernetes events and application behavior as independent observations.
4. Trace alert evaluation and notification configuration when needed. `apps/monitoring/victoria-metrics/cluster/vmalert.yaml` defines evaluation and notifier selection. Rules live with workloads or the monitoring stack. `apps/monitoring/alertmanager/app/` owns Alertmanager and notification routing.
5. After an authorized fix, verify the original symptom, recovery in telemetry, and relevant alert resolution. State remaining uncertainty and unverified delivery paths.

The configured notification route sends ordinary alerts to Pushover, Watchdog to Healthchecks, and InfoInhibitor to a blackhole receiver. Inspect the manifests for exact grouping, inhibition, and timing before diagnosing missing notifications. An empty Alertmanager response alone does not prove rule evaluation or notification delivery is healthy.

`TargetDown` alerts for each scrape target that fails continuously for ten minutes. Targets labeled `availability="on-demand"` are excluded. Check the rule with `bash k8s/apps/monitoring/victoria-metrics/k8s-stack/tests/test.sh` using `promtool` and `yq` from the development shell.

AM6B's exporter is owned by CoreELEC's native Kodi add-on. See the
[CoreELEC monitoring runbook](../docs/coreelec-monitoring.md) when restoring it
after changing the device's boot storage.

`InternetUnavailable` fires when TCP probes to both `1.1.1.1:443` and `8.8.8.8:443` fail for two minutes. Both targets must have metrics; missing scrapes or a single provider failure do not trigger inhibition. While firing, it inhibits Flux source readiness alerts, internet and upstream DNS probe failures, and container waiting alerts with `ErrImagePull` or `ImagePullBackOff`. Inhibition applies across namespaces. Local device and DNS probes, Flux controller health, workload readiness, and backup alerts remain visible. Check the internet rule with `bash k8s/apps/monitoring/blackbox-exporter/tests/test.sh` using `promtool` and `yq` from the development shell.

Keep durable alert changes in manifests. Prefer actionable symptoms with useful labels and annotations. Validate that metrics exist and that the rule evaluates as intended; rendering YAML alone cannot establish this. Do not create test incidents or send test notifications without task authorization. Use the Katl runbook for maintenance silences within an authorized node-maintenance workflow.
