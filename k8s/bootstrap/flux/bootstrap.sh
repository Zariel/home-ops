#!/usr/bin/env /bin/bash

set -euo pipefail

kubectl apply --server-side --filename https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.71.2/example/prometheus-operator-crd/monitoring.coreos.com_podmonitors.yaml
kubectl apply --server-side --filename https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.71.2/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
kubectl apply --server-side --filename https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.71.2/example/prometheus-operator-crd/monitoring.coreos.com_scrapeconfigs.yaml
kubectl apply --server-side --filename https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.71.2/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml

kubectl apply --kustomize ./
sops --decrypt sops-age.sops.yaml | kubectl apply -f -
sops --decrypt github-deploy-key.sops.yaml | kubectl apply -f -

# off we go
kubectl apply --kustomize ../../flux/config
