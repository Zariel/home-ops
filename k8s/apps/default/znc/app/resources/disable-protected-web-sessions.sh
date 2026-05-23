#!/bin/sh
set -eu

config=/config/configs/znc.conf

if [ ! -f "$config" ]; then
  exit 0
fi

if grep -q '^ProtectWebSessions[[:space:]]*=' "$config"; then
  sed -i 's/^ProtectWebSessions[[:space:]]*=.*/ProtectWebSessions = false/' "$config"
  exit 0
fi

tmp=$(mktemp)
awk '
  !done && /^LoadModule[[:space:]]/ {
    print "ProtectWebSessions = false"
    done = 1
  }
  { print }
  END {
    if (!done) {
      print "ProtectWebSessions = false"
    }
  }
' "$config" > "$tmp"
cat "$tmp" > "$config"
rm -f "$tmp"
