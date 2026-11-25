# Home Ops

Personal home-ops repo for my homelab. This repository tracks my Kubernetes and supporting infrastructure as code.

## Overview

- GitOps config lives under `k8s/` (Flux bootstrap, cluster/global config, apps, and reusable components)
- Katl cluster configuration and the migration/runbook are in [`katl/`](katl/README.md)
- `truenas/` contains TrueNAS-related assets
- Task automation is defined in `Taskfile.yaml` and `.taskfiles/`

## Repository guidance

- [Agent instructions](AGENTS.md): working rules, validation, and operational permissions.
- [Kubernetes conventions](k8s/README.md): manifest organization, secret ownership, network trust, and Pocket ID integration.
- [Observability operations](k8s/OPERATIONS.md): Grafana metrics and logs, Alertmanager access, and incident investigation.

## Network architecture

This homelab is fully L3 routed. Cluster nodes are not on a shared L2 domain.

The host service addressing policy, kept in the infra workspace as
`docs/host-services.md`, reserves
`10.5.0.0/16`, with one routed `/26` per host. It also records the staged gateway
migration and the Kubernetes NTP and monitoring consumer changes.

### Loopback Addressing

Loopbacks live in `10.254.254.0/24` and are carved by role:
- `10.254.254.0/26`: L3 switches
- `10.254.254.64/26`: Hypervisors / routers
- `10.254.254.128/26`: Kubernetes nodes
- `10.254.254.192/26`: Reserved / future

## Hardware

### Kubernetes Nodes (3)

- 3x MinisForum MS01 (k8s-0, k8s-1, k8s-2)
  - Intel i9-12900H
  - 64GB DDR5 (2x32GB)
  - 1x Samsung PM983 3.8TB U.2
  - 2x Samsung PM983 960GB M.2
  - 1x Mellanox ConnectX-4 Lx

### Proxmox Host

- pve1
  - AMD EPYC 7302P
  - Supermicro H11
  - 256GB DDR4 ECC RDIMM (8x32GB)
  - 2x Samsung PM893 SATA (boot / Proxmox OS)
  - 2x Samsung PM963 3.8TB U.2 (ZFS mirror for VM storage)
  - 1x Mellanox ConnectX-4 Lx

### TrueNAS VM (on pve1)

- LSI-9400-16i HBA passthrough
  - 12x Seagate Exos 16TiB
- Intel Optane P4800X 360GB U.2 (SLOG)
- 2x Samsung PM983 3.8TB U.2 (L2ARC)
- 2x Samsung PM963 960GB U.2 + M.2 (metadata)
- 128GB RAM

TrueNAS only serves the LAN, so its `net.ipv4.tcp_congestion_control` sysctl
tunable (System → Advanced Settings → Sysctl) is `cubic`. The tunable lives in
the TrueNAS configuration, not in this repository. Cluster nodes choose
[congestion control per route](katl/README.md#retained-configuration).
