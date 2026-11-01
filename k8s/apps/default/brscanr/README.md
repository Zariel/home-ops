# brscanr

brscanr v0.1.0 runs separately from Paperless and uses ordinary routed pod networking. It registers with the Brother printer at `10.1.2.70` as `BrscanrTest` during validation.

## Rollout status

Registration and Paperless API authentication have been verified. Physical acquisition, feeder page order, Paperless import, and the physical Scan to PC callback still require test pages and an operator button press.

The public route at <https://brscanr.cbannister.xyz> requires Pocket ID membership in `admin`. It deliberately targets the empty `brscanr-pending` Service until hardware validation completes. Envoy protects every HTTP path, including the JSON API and retained PDFs. Authentication must be renewed after the 15-minute access token expires.

Keep the existing Paperless scanner sidecar and LAN attachment until physical validation succeeds. Then remove the sidecar, its mounts, the trusted-LAN annotation and the Multus dependency. Preserve the Paperless PVC and its retained `scanner-spool` artifacts. Stop the old destination owner and allow its registration lease to expire before reusing its destination name.

After validating authentication, change the HTTPRoute backend to `brscanr:8080` and remove the pending Service. Do not expose the HTTP Service directly: brscanr has no built-in authentication.

## Network requirements

| Source | Destination | Purpose |
| --- | --- | --- |
| brscanr | `10.1.2.70:443/TCP` | Register the destination |
| brscanr | `10.1.2.70:54921/TCP` | Acquire pages |
| `10.1.2.70` | `10.45.0.25:54925/UDP` | Physical button callback |
| brscanr | Internal Envoy HTTPS listener | Paperless API |
| External Envoy | brscanr HTTP Service | Authenticated web access |

The callback Service uses `externalTrafficPolicy: Local` to preserve the printer's source address. Cilium and the application restrict callbacks to that source. Cilium restricts HTTP access to the external gateway and local host probes.

VyOS `transit-trusted` rule 110 permits the two printer TCP ports from pod networks. Maintain it in `../vyos-config/config-parts/firewall-ipv4-transit.sh`. The existing `trusted-transit` load-balancer rule permits callbacks. The printer's self-signed certificate requires disabling certificate verification only for printer registration; Paperless HTTPS verification remains enabled.

## Storage and recovery

The `brscanr` PVC contains the spool and delivery database and is backed up by VolSync. Keep this PVC when replacing pods. Never run two owners for the same printer destination, and fence an unreachable old owner before forcing replacement after a node partition.

The dedicated Paperless `brscanr` account has an unusable password, no staff or superuser privileges, and only `add_document`, `view_document` and `view_paperlesstask` permissions. Its token is encrypted in `app/paperless.secret.sops.yaml`.

For private diagnostics, run this from the repository root:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl -n default port-forward service/brscanr 18080:8080 --address=127.0.0.1
```

Read `http://127.0.0.1:18080/api/status` for registration and callback observations and `/api/jobs` for acquisition and delivery state. Successful registration alone does not prove scanning or import works. If delivery acceptance is uncertain, reconcile the existing Paperless task or document before retrying to avoid duplicates. See the [upstream operations guide](https://github.com/Zariel/brscanr/blob/v0.1.0/docs/operations.md).
