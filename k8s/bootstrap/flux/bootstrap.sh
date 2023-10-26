#!/usr/bin/env /bin/bash

set -euo pipefail

kubectl apply --kustomize ./
sops --decrypt sops-age.sops.yaml | kubectl apply -f -
sops --decrypt github-deploy-key.sops.yaml | kubectl apply -f -

# off we go
kubectl apply --kustomize ../../flux/config
