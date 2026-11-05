#!/usr/bin/env bash
set -euo pipefail

test_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test_tmp=$(mktemp -d)
trap 'rm -rf -- "$test_tmp"' EXIT

yq '.spec' "$test_dir/../vmrule.yaml" > "$test_tmp/rules.yaml"
cp "$test_dir/rules.test.yaml" "$test_tmp/tests.yaml"
cd "$test_tmp"
promtool test rules tests.yaml
