#!/usr/bin/env bash

set -euo pipefail

# User-defined variables
CROSS_SEED_HOST="${CROSS_SEED_HOST:-required}"
CROSS_SEED_PORT="${CROSS_SEED_PORT:-required}"
CROSS_SEED_API_KEY="${CROSS_SEED_API_KEY:-required}"
CROSS_SEED_SLEEP_INTERVAL="${CROSS_SEED_SLEEP_INTERVAL:-30}"

# Function to set release variables from SABnzbd
set_sab_vars() {
    RELEASE_NAME="${SAB_FILENAME:-}"
    RELEASE_DIR="${SAB_COMPLETE_DIR:-}"
    RELEASE_CAT="${SAB_CAT:-}"
    RELEASE_SIZE="${SAB_BYTES:-}"
    RELEASE_STATUS="${SAB_PP_STATUS:-}"
    RELEASE_INDEXER="${SAB_URL:-}"
    RELEASE_TYPE="NZB"
}

# Function to set release variables from qBittorrent
set_qb_vars() {
    RELEASE_NAME="$1"      # %N
    RELEASE_DIR="$2"       # %F
    RELEASE_CAT="$3"       # %L
    RELEASE_SIZE="$4"      # %Z
    RELEASE_INDEXER="$5"   # %T
    RELEASE_STATUS=0       # Always 0 for qBittorrent
    RELEASE_TYPE="Torrent"
}

# Function to search for cross-seed
search_cross_seed() {
    local status_code
    status_code=$(curl \
        --silent \
        --output /dev/null \
        --write-out "%{http_code}" \
        --request POST \
        --data-urlencode "path=${RELEASE_DIR}" \
        --header "X-Api-Key: ${CROSS_SEED_API_KEY}" \
        "http://${CROSS_SEED_HOST}:${CROSS_SEED_PORT}/api/webhook"
    )

    printf "cross-seed search returned with HTTP status code %s and path %s\n" \
        "${status_code}" \
        "${RELEASE_DIR}" >&2

    sleep "${CROSS_SEED_SLEEP_INTERVAL}"
}

main() {
    # Determine the source and set release variables accordingly
    if env | grep -q "^SAB_"; then
        set_sab_vars
    else
        set_qb_vars "$@"
    fi

    # Check if post-processing was successful
    if [[ "${RELEASE_STATUS}" -ne 0 ]]; then
        printf "post-processing failed with sabnzbd status code %s\n" \
            "${RELEASE_STATUS}" >&2
        exit 1
    fi

    if [[ "${RELEASE_CAT}" == "cross-seed" ]]; then
        echo "ignoring cross-seed search for already cross-seeded download ${RELEASE_NAME}"
        exit 0
    fi

    # Update permissions on the release directory
    chmod -R 777 "${RELEASE_DIR}"

    # Search for cross-seed
    search_cross_seed
}

main "$@"
