# DNS dashboards

The DNS folder contains five dashboards after rollout:

| Dashboard | Purpose |
| --- | --- |
| DNS / Overview | Answer checks, DNS node coverage, filtering traffic, backend health and routing logs |
| Blocky / Overview | Node/client/outcome filters, query logs, list freshness and winning upstreams |
| BIND9 / Overview | Pod health, responses, primary/secondary serial comparison and transfer/update logs |
| DNSdist / Overview | Node/backend filters, latency, errors, outstanding requests and separate pool caches |
| External DNS | Existing record reconciliation dashboard, retained |

The imported DNSdist resource is replaced in place, preserving UID
`c8a04601-b1d2-4085-9407-98ffadd0ab27` and its existing links. Its old queries
incorrectly applied rates to outstanding-query and dynamic-block-size gauges.
CoreDNS is intentionally excluded from the DNS dashboards. The existing CoreDNS
dashboard stays in the Kubernetes folder; Hubble remains in Cilium.

## Ownership and rollout

All Kubernetes changes are Flux managed. No live dashboards or workloads were
changed during preparation. The `grafana-dashboards` unit owns the stable
`dns-dashboards` ConfigMap. The existing DNSdist GrafanaDashboard in the `grafana`
unit references it; the operator retries until that ConfigMap exists. The other
three GrafanaDashboard resources live in `grafana-dashboards`.

The monitoring cluster unit adds native Blocky/DNSdist scrapes against stable
node addresses (10.254.53.0, .2 and .4), labelled dns-1, dns-2 and dns-3.
BIND primary and secondary units add bind-exporter v0.8.0 sidecars and
PodMonitors. Each statistics channel binds only to pod loopback. The blackbox
unit adds six UDP/TCP DNS answer probes, using the existing exporter and Probe
collection. These probes also participate in the existing BlackboxProbeFailed
rule; no alert rules or notification settings are changed.

After the changes are committed and pushed through the normal review process,
reconcile the affected Flux units and allow several scrape intervals for rates.
Verify three endpoints each for Blocky and DNSdist, three BIND exporters, six
DNS probes, and matching observations for both hosted zones across all BIND pods.
The BIND configuration changes cause rolling replacement (primary uses Recreate).
No secrets or new externally exposed endpoints are needed.

The accompanying `../nix-ops/roles/server/vector.nix` change forwards all Blocky
queries instead of only abnormal ones. Existing unrelated edits are preserved.
It requires a separately authorized NixOS rollout. Earlier allowed queries cannot
be recovered; their absence before rollout is expected. All-query forwarding
increases log volume and retains client/domain history under existing retention.

Rollback by reverting the dashboard, scrape, probe and BIND exporter changes in
Git, and reverting the all-query forwarding change separately in nix-ops.

## Reading the dashboards

- Top tiles lead with health, followed by everyday traffic and upstream panels.
  Diagnostic rows are collapsed. Defaults are 24 hours and a one-minute refresh,
  following https://github.com/buroa/grafana-dashboards/blob/main/AGENTS.md.
- DNS traffic is shown by layer, never summed across layers. One query can pass
  through DNSdist, Blocky or BIND.
- Blocky client charts and logs omit the local 127.0.53.20 health-check client.
  Client/outcome filters affect client counters and query logs. Service-wide
  metrics and service logs remain scoped to the selected host, as described.
- Blocky logs retain client IP/name, question, response code/type and reason.
  Domain accepts a regular expression; expand a log entry for structured fields.
- DNSdist backend status uses lazy health checks and may be stale on idle paths.
  Backend latency is milliseconds; overall average latency is microseconds.
- Blocky's `reason` label identifies the winning DoT resolver. It does not expose
  every parallel attempt or independent availability for all four upstreams.
- BIND serial spread must be read with zone observation counts: equal serials on
  two replicas do not prove a missing third replica is synchronized. Zone filters
  apply to serial panels; pod filters apply to traffic and logs.
- VIP probes run inside Kubernetes. They verify local-zone and unfiltered upstream
  resolution, not every VLAN, IPv6 path or trusted-client filtering path.
- Missing telemetry displays No data, never an invented healthy zero. Local node
  BIND and BGP/VIP routing have backend checks and service logs; they do not have
  dedicated BIND/BGP metrics in this change.

## Validation

Preparation checks on 2026-11-09:

- All changed Kustomizations render and pass server-side dry-run validation.
- Four dashboards pass dashboard-linter v0.5.2 strict mode with `resources/dns.lint`.
  The five documented exclusions concern datasource naming and job/instance
  plumbing; host/pod selectors intentionally replace scrape-address selectors.
- All 62 panel queries pass the live VictoriaMetrics/VictoriaLogs APIs. Only
  already-collected telemetry returns data; newly added scrapes/probes and BIND
  metrics require rollout before result semantics can be verified end to end.
- All six native Blocky 0.35.0 and DNSdist 2.0.10 metric endpoints are reachable;
  metric names, labels and types were checked against those endpoints.
- Both BIND configurations pass `named-checkconf` in the running BIND 9.21.4
  containers. bind-exporter metric names and JSON statistics support were checked
  against its v0.8.0 source and the running BIND build.
- Expected VIP and cluster BIND answers were checked over UDP/TCP. CoreDNS returns
  172.21.0.1 over both transports from an existing in-cluster BIND container.
- The modified Vector Nix file parses; no NixOS build or deployment was performed.
- Visual Grafana rendering and post-rollout verification remain outstanding;
  the local Docker daemon is unavailable. No screenshot-based QA is claimed.

Run the dashboard lint checks from this directory:

```sh
for dashboard in dns-overview blocky bind9 dnsdist; do
  dashboard-linter lint --strict -c resources/dns.lint "resources/$dashboard.json"
done
```

## Rollout verification

Published and reconciled through Flux on 2026-11-09. All six native DNS-node
scrapes and all three BIND exporters report healthy. Both hosted zones have
three matching serial observations. The Grafana operator reports all four
dashboards synchronized. All 62 original panel queries were checked after rollout:
56 returned data, with the remaining error/log panels empty. BIND trims the Qry
prefix from response labels; the SERVFAIL filter was corrected to match. Zone
selection is limited to the two hosted zones to omit automatic empty reverse zones.

CoreDNS was subsequently removed from the DNS overview at operator request; its
existing dashboard remains in Kubernetes. Screenshot QA is unavailable: Grafana's
renderer returns HTTP 500 and no browser connection is available. All-query
Blocky log forwarding still requires the separate NixOS rollout.
