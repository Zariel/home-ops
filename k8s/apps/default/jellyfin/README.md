# Jellyfin

Jellyfin serves local accounts at `https://jellyfin.cbannister.xyz` through the external HTTPS gateway. Plex remains available independently.

## Complete private setup

The Service has no ready endpoints until Jellyfin reports that its setup wizard is complete. Envoy panic routing is disabled for this backend so it cannot fall back to unready endpoints. The public hostname returns `503` during setup, including after configuration loss. Keep `healthCheck.panicThreshold: 0`, do not enable `publishNotReadyAddresses`, and do not replace the readiness probe with `/health`.

From the repository root, forward directly to the running Deployment:

```sh
KUBECONFIG="$PWD/kubeconfig" kubectl --namespace default port-forward deployment/jellyfin 8096:8096 --address=127.0.0.1
```

Open `http://127.0.0.1:8096` and complete the wizard:

1. Create a dedicated administrator with a unique, strong password. Store it in your password manager.
2. Add movie and TV libraries from `/data/media/films` and `/data/media/tv`. Other media directories are also mounted read-only under `/data/media`.
3. Allow remote access and leave automatic port mapping disabled.
4. Finish the wizard. Within one readiness-probe interval, the public hostname starts serving Jellyfin.

Keep the port-forward open while configuring accounts in **Dashboard > Users**:

- Hide the administrator from login screens and disable its remote access. Use the private port-forward for administration.
- Create separate, non-administrator accounts for viewers, with remote access enabled and only the required libraries selected.
- Hide viewer accounts from login screens and set a finite failed-login limit, such as `5`. Unlocking an account requires an administrator.
- Disable content deletion, downloads, public sharing, Live TV management, and control of other users' sessions unless the viewer needs those features. Keep video/audio transcoding and remuxing enabled for client compatibility.

Verify a viewer can sign in and play media at the public hostname, then stop the port-forward. This deployment uses local accounts; no OIDC plugin is installed.

## Isolation and storage

The container runs as UID/GID `568`, drops all capabilities, uses the runtime seccomp profile, has a read-only root filesystem, and receives no Kubernetes service-account token. Only the external Envoy pods, Sonarr, Radarr, Wizarr, and the hosting node can reach TCP `8096`; discovery ports and direct LAN ingress are not exposed.

Sonarr and Radarr can send library-update notifications to `http://jellyfin.default.svc.cluster.local:8096` using a Jellyfin API key. The network policy grants connectivity; Jellyfin still authenticates API requests.

Wizarr can use the same internal URL with its own Jellyfin API key to manage invitations. Set its public Jellyfin URL to `https://jellyfin.cbannister.xyz` for viewers.

Outbound connections are restricted to cluster DNS and HTTPS for TMDb, OMDb, TVDB artwork (`artworks.thetvdb.com`), and studio images (`raw.githubusercontent.com`). The GitHub hostname allowance also permits other content hosted on that hostname. Other destinations, including plugin repositories, remote streams, and arbitrary LAN/Internet connections, are blocked. The plugin directory is read-only, including built-in provider settings. Their default configuration is seeded before startup; installing plugins or changing provider settings requires a manifest change.

Network and encoding settings in `app/config/` seed an empty configuration volume. Subsequent dashboard settings persist in the `jellyfin` Ceph PVC, backed up through the shared VolSync component. Cache, logs, temporary files, and transcoding output are disposable and size-limited. Media mounts are read-only at both the NFS volume and container mount.

The pod CIDR is trusted for forwarded headers. Ingress is limited to the external gateway, the hosting node, and the trusted Sonarr, Radarr, and Wizarr automation clients. Review proxy trust before allowing additional callers. The shared Envoy access-log format removes query strings, which can contain media-client tokens. Authentication and password-reset requests share a limit of 20 requests per minute per Envoy replica; playback requests are outside that limit.

## Shared transcoding GPU

The `common` Flux Kustomization owns `default/transcode-gpu`. Plex, Jellyfin, and Immich microservices reference that same ResourceClaim, so they share one iGPU and run on its selected node. The claim does not divide or guarantee GPU throughput. Immich machine learning retains its own allocation; the DRM exporter uses administrative access.

The shared claim retains its node allocation across pod restarts. Node replacement or permanent node failure requires an operator-planned claim replacement after stopping its consumers; ordinary pod rescheduling does not move the allocation to another node.

Jellyfin seeds Intel Quick Sync acceleration and writes transcoding output to `/transcode`. Confirm hardware transcoding with a representative client after creating a viewer account. Successful pod startup alone does not verify playback compatibility.
