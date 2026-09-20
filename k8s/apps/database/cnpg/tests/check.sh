#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
yq '.spec' "$source_dir/../pg18vc/prometheusrule.yaml" > "$test_dir/rules.yaml"
cp "$source_dir/alerts.test.yaml" "$test_dir/alerts.test.yaml"
cd "$test_dir"
promtool check rules rules.yaml
promtool test rules alerts.test.yaml
