# Repository Guidelines

## Working Principles
- Make the smallest change necessary and preserve unrelated worktree changes.
- Verify assumptions from repository or live-cluster state. Research ambiguous points and ask when the answer would materially change the result.
- Before a hard-to-reverse infrastructure or architectural decision, establish the requirement and constraints, then compare materially different ownership or implementation models. Prefer existing primitives and derived state over custom reconciliation.
- Revisit the chosen approach if new information invalidates an assumption or its complexity grows unexpectedly.

## Repository Structure
- Kubernetes GitOps configuration lives in `k8s/`: `bootstrap/` for initial bootstrap, `flux/` for cluster-level Flux resources, `apps/` for workloads, and `components/` for reusable Kustomize components.
- Talos configuration lives in `talos/`. Ansible playbooks and inventory live under `ansible/main/`.
- Task automation starts at `Taskfile.yaml`, with task groups under `.taskfiles/`.
- `age.key`, `kubeconfig.yaml`, and `talos/clusterconfig/talosconfig` are ignored local credentials/configuration. Never commit them.

## Common Commands
- List tasks: `task`
- Set up Ansible: `task ansible:venv`
- Run a playbook: `task ansible:run playbook=<name> -- --extra-vars "cluster=<id>"`
- Configure Matchbox: `task ansible:matchbox -- --extra-vars "cluster=<id>"`
- Generate Talos configuration: `task talos:generate`

Prefer task wrappers so repository paths, `KUBECONFIG`, and `SOPS_AGE_KEY_FILE` are set consistently.

## Conventions and Secrets
- Use 2-space indentation in YAML and explicit namespaces in Kubernetes resources.
- Use Kustomize components for genuinely shared configuration, notably `k8s/components/common` and `k8s/components/volsync`.
- Encrypted secrets must match a creation rule in `.sops.yaml`; never add plaintext secrets.
- Follow `ansible/.ansible-lint` and prefer Ansible modules over raw shell or command tasks.

## Validation
- Render each changed Kustomization with `kubectl kustomize <path>`.
- When cluster-aware validation is useful, run `kubectl apply --dry-run=server -k <path>`; do not use a non-dry-run apply for GitOps-managed resources.
- Ensure required CRDs exist and add `spec.dependsOn` only when reconciliation ordering is required.
- For Ansible, use `--check --diff --limit <host-or-group>` when the playbook supports check mode. Start with the narrowest target.

## Git and Pull Requests
- Keep one logical change per commit and stage only files belonging to the completed task.
- When asked to commit, use `git commit-wrapped`; pass the title and body as plain arguments and use `git commit-wrapped --amend` when amending.
- Prefer conventional titles such as `fix(container): update image`; use present tense and a concrete scope.
- PR descriptions should cover impact, validation, rollout or rollback, and required secret/configuration changes.

## Cluster and Operational Safety
- The Kubernetes cluster is available through `kubectl`. Use read-only queries by default.
- Persistent Kubernetes changes belong in Git and are applied by Flux. Do not use `kubectl apply`, `edit`, `patch`, or `delete` to bypass GitOps unless the operator explicitly requests it.
- Agents may run `flux reconcile` and observe the rollout without separate operator approval.
- Grafana is available at `https://grafana.cbannister.xyz` and exposes metrics and VictoriaLogs data.
- `kubectl node-shell -x -n kube-system <node>` creates a privileged pod with host access; use it only with explicit operator direction.
- Agents may edit or generate Talos configuration, but must not apply machine configuration, upgrade, reset, or bootstrap Talos nodes. Ask the operator to perform or coordinate those actions.
- `task rook:reset` destroys Ceph data and disk contents. Never run it unless the operator explicitly requests it and the exact nodes and disk have been verified.
