#!/usr/bin/env bash
set -euo pipefail

app_dir="k8s/apps/default/forgejo/app"
kustomization="${app_dir}/kustomization.yaml"
theme_file="${app_dir}/themes/theme-catppuccin-mocha-lavender.css"
theme_name="$(basename "${theme_file}")"
override_file=".renovate/scripts/forgejo-catppuccin-overrides.css"

version="$(awk '/catppuccin-gitea:/ { print $3; exit }' "${kustomization}")"

if [[ -z "${version}" ]]; then
  echo "Unable to find catppuccin-gitea version in ${kustomization}" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

archive="${tmp_dir}/catppuccin-gitea.tar.gz"
curl -fsSL \
  "https://github.com/catppuccin/gitea/releases/download/${version}/catppuccin-gitea.tar.gz" \
  -o "${archive}"

tar -xzf "${archive}" -C "${tmp_dir}" "./${theme_name}"
cp "${tmp_dir}/${theme_name}" "${theme_file}"
printf "\n\n" >> "${theme_file}"
cat "${override_file}" >> "${theme_file}"
