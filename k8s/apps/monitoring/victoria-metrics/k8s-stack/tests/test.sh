#!/usr/bin/env bash
set -euo pipefail

test_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test_tmp=$(mktemp -d)
trap 'rm -rf -- "$test_tmp"' EXIT

# Select the HelmRelease in a separate pass: yq still constructs the rule group
# for the file's other documents, and promtool reads only the first document.
yq 'select(.kind == "HelmRelease")' "$test_dir/../helmrelease.yaml" |
  yq '.spec.values.defaultRules.rules.TargetDown.spec | {"groups": [{"name": "target-down.rules", "rules": [. + {"alert": "TargetDown"}]}]}' \
  > "$test_tmp/rules.yaml"
cp "$test_dir/rules.test.yaml" "$test_tmp/tests.yaml"
cd "$test_tmp"
promtool test rules tests.yaml
