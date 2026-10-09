#!/bin/sh
set -eu

: "${SCANNER_IP:?SCANNER_IP must be set}"
: "${CALLBACK_IP:?CALLBACK_IP must be set}"

brsaneconfig5 -a name=Brother model=MFC-L2800DW "ip=$SCANNER_IP"

# Brother's callback address must be reachable from the printer, not a pod IP.
python3 - "$CALLBACK_IP" <<'PY'
import pathlib
import sys

config = pathlib.Path('/opt/brother/scanner/brscan-skey/brscan-skey.config')
config.write_text(
    f'ip_address={sys.argv[1]}\n'
    'user=Paperless\n'
    'password=\n'
    'IMAGE="/usr/local/bin/scan-to-paperless"\n'
    'OCR="/usr/local/bin/scan-to-paperless"\n'
    'EMAIL="/usr/local/bin/scan-to-paperless"\n'
    'FILE="/usr/local/bin/scan-to-paperless"\n'
    'SEMID=b\n'
)
PY

mkdir -p /consume /scan-spool
echo "Registering Paperless scan destination for $SCANNER_IP at $CALLBACK_IP:54925"
exec /opt/brother/scanner/brscan-skey/brscan-skey-exe -f "$@"
