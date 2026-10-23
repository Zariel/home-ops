#!/bin/sh
set -eu

config=/config/configs/znc.conf

if [ ! -f "$config" ]; then
  exit 0
fi

if grep -q '^LoadModule[[:space:]]*=[[:space:]]*modpython\([[:space:]]\|$\)' "$config"; then
  exit 0
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
{
  printf 'LoadModule = modpython\n'
  cat "$config"
} > "$tmp"

# Startup runs before ZNC; preserve the configuration file's ownership and mode.
cat "$tmp" > "$config"
