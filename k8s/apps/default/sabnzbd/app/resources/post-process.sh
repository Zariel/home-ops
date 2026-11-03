#!/usr/bin/env bash
# shellcheck disable=SC2154

set -euo pipefail

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


# replaces spaces with dot's in release file names which apparently
# helps prevent loops with poorly named releases (HONE)
replace_spaces() {
    local replaced
    local original
    for name in "${RELEASE_DIR}"/*; do
        original=$(basename "$name")
        replaced="${original//_/.}"
        if [[ "$replaced" != "$original" ]]; then
            mv -v "$RELEASE_DIR/$original" "$RELEASE_DIR/$replaced"
        fi
    done
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

    # Update permissions on the release directory
    chmod -R 750 "${RELEASE_DIR}"

    replace_spaces
}

main "$@"
