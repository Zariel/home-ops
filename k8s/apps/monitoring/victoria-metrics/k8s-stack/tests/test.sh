#!/usr/bin/env bash
set -euo pipefail

test_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test_tmp=$(mktemp -d)
trap 'rm -rf -- "$test_tmp"' EXIT

yq 'select(.kind == "HelmRelease") | .spec.values.defaultRules.rules.TargetDown.spec | {"groups": [{"name": "target-down.rules", "rules": [. + {"alert": "TargetDown"}]}]}' \
  "$test_dir/../helmrelease.yaml" > "$test_tmp/rules.yaml"
cp "$test_dir/rules.test.yaml" "$test_tmp/tests.yaml"
cd "$test_tmp"
promtool test rules tests.yaml
