# CoreELEC node exporter

AM6B is scraped at `am6b.cbannister.casa:9100` by
[`node-exporter.yaml`](../k8s/apps/monitoring/victoria-metrics/cluster/scrapeconfigs/node-exporter.yaml).
CoreELEC's official `service.prometheus-node-exporter` Kodi add-on owns the
exporter binary, settings, and enabled systemd service on the device. Flux owns
the scrape configuration. Install the add-on on each new CoreELEC storage volume;
booting a trial USB does not inherit add-ons from the internal installation.

## Restore monitoring

In Kodi, install **Prometheus Node Exporter** from **CoreELEC Add-ons → Services**.
Use the repository supplied by the running CoreELEC release and architecture.
Keep its default port `9100` and path `/metrics`.

Alternatively, request the same native installation over SSH, then accept the
add-on confirmation in Kodi:

```sh
ssh -S none -o ControlMaster=no root@am6b.cbannister.casa \
  'kodi-send --action="InstallAddon(service.prometheus-node-exporter)"'
```

Verify the add-on's persistent service and endpoint:

```sh
ssh -S none -o ControlMaster=no root@am6b.cbannister.casa \
  'systemctl is-enabled service.prometheus-node-exporter; systemctl is-active service.prometheus-node-exporter'
curl --fail --silent --show-error http://am6b.cbannister.casa:9100/metrics
```

In VictoriaMetrics, verify `up{instance="am6b.cbannister.casa:9100"} == 1`
and that `TargetDown` resolves. A reachable SSH service does not establish
exporter health. Disabling or uninstalling the add-on through Kodi rolls back
the device change and stops monitoring.

## Recovery on 2026-11-17

The CoreELEC 22.0-Piers_rc2 USB trial was reachable but lacked the exporter
add-on. Installed version `22.0.13.0` from its bundled official repository
(`Amlogic-no/22.0.12/aarch64`), which provides node_exporter `1.12.1`.
Verified the service is active and enabled, `/metrics` responds, and the
VictoriaMetrics scrape returns `up=1`. No reboot is required.
