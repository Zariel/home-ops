#!/bin/sh

# qBittorrent Web API credentials
QB_URL="http://qbittorrent.default.svc.cluster.local"

TORRENT_HASH="$1"  # Get the torrent hash directly from autobrr

# Ensure a hash was provided
if [ -z "$TORRENT_HASH" ]; then
  echo "Error: No torrent hash provided"
  exit 1
fi

# Force reannounce using the hash from autobrr
# Check the result of the reannounce action
if ! curl -f -X POST "$QB_URL/api/v2/torrents/reannounce" --data "hashes=$TORRENT_HASH"; then
  echo "Error: Failed to reannounce torrent with hash $TORRENT_HASH"
  exit 1
fi

echo "Success: Reannounced torrent with hash $TORRENT_HASH"

# Exit with a success status code
exit 0
