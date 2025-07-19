#!/usr/bin/env bash

if  sops filestatus trackers.sops.cue; then
  sops -i -d trackers.sops.cue
fi

set -euo pipefail

cue export --outfile=config.sops.yaml -f

sops -i -e trackers.sops.cue
sops -i -e --input-type=binary config.sops.yaml
