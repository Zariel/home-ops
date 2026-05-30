#!/usr/bin/env bash
set -euo pipefail

VAULT="Kubernetes"
ITEM="flatcar-kubeadm-hollywoo"
CREATE_VAULT=false
FORCE=false
KEEP_FILES=false
SSH_PUBLIC_KEY_FILE=""

usage() {
  cat <<EOF
Usage: flatcar/scripts/populate-kubeadm-secrets.sh [options]

Generates kubeadm bootstrap material and stores it in 1Password fields read by
flatcar/render.sh.

Options:
  --vault NAME             1Password vault name (default: Kubernetes)
  --item NAME              1Password item name (default: flatcar-kubeadm-hollywoo)
  --ssh-public-key FILE    Use an existing SSH public key instead of generating a keypair
  --create-vault           Create the vault if it does not exist
  --force                  Update an existing item, rotating generated values
  --keep-files             Keep generated files and print their temporary directory
  -h, --help               Show this help

The script writes generated values to temporary files and passes file paths to
1Password, avoiding secret values in command arguments.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault)
      VAULT="$2"
      shift
      ;;
    --item)
      ITEM="$2"
      shift
      ;;
    --ssh-public-key)
      SSH_PUBLIC_KEY_FILE="$2"
      shift
      ;;
    --create-vault)
      CREATE_VAULT=true
      ;;
    --force)
      FORCE=true
      ;;
    --keep-files)
      KEEP_FILES=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

need op
need openssl
need ssh-keygen

if [[ -n "$SSH_PUBLIC_KEY_FILE" && ! -f "$SSH_PUBLIC_KEY_FILE" ]]; then
  echo "SSH public key file not found: $SSH_PUBLIC_KEY_FILE" >&2
  exit 1
fi

tmp=$(mktemp -d)
chmod 0700 "$tmp"
cleanup() {
  if [[ "$KEEP_FILES" == true ]]; then
    echo "kept generated files in $tmp" >&2
  else
    rm -rf "$tmp"
  fi
}
trap cleanup EXIT

if ! op vault get "$VAULT" >/dev/null 2>&1; then
  if [[ "$CREATE_VAULT" == true ]]; then
    op vault create "$VAULT" >/dev/null
  else
    echo "1Password vault not found: $VAULT" >&2
    echo "rerun with --create-vault to create it" >&2
    exit 1
  fi
fi

printf '%s.%s\n' "$(openssl rand -hex 3)" "$(openssl rand -hex 8)" > "$tmp/kubeadm-token"
openssl rand -hex 32 > "$tmp/kubeadm-certificate-key"

openssl genrsa -out "$tmp/kubernetes-ca-key" 4096 >/dev/null 2>&1
chmod 0600 "$tmp/kubernetes-ca-key"
openssl req -x509 -new -nodes \
  -key "$tmp/kubernetes-ca-key" \
  -subj "/CN=kubernetes-ca" \
  -days 3650 \
  -out "$tmp/kubernetes-ca-crt" >/dev/null 2>&1

if [[ -n "$SSH_PUBLIC_KEY_FILE" ]]; then
  cp "$SSH_PUBLIC_KEY_FILE" "$tmp/ssh-public-key"
else
  ssh-keygen -t ed25519 -C flatcar-core -f "$tmp/ssh-private-key" -N '' >/dev/null
  cp "$tmp/ssh-private-key.pub" "$tmp/ssh-public-key"
fi

args=(
  "kubeadm-token[file]=$tmp/kubeadm-token"
  "kubeadm-certificate-key[file]=$tmp/kubeadm-certificate-key"
  "kubernetes-ca-crt[file]=$tmp/kubernetes-ca-crt"
  "kubernetes-ca-key[file]=$tmp/kubernetes-ca-key"
  "ssh-public-key[file]=$tmp/ssh-public-key"
)

if [[ -f "$tmp/ssh-private-key" ]]; then
  args+=("ssh-private-key[file]=$tmp/ssh-private-key")
fi

if op item get "$ITEM" --vault "$VAULT" >/dev/null 2>&1; then
  if [[ "$FORCE" != true ]]; then
    echo "1Password item already exists: op://$VAULT/$ITEM" >&2
    echo "rerun with --force to replace these fields with newly generated values" >&2
    exit 1
  fi

  op item edit "$ITEM" --vault "$VAULT" "${args[@]}" >/dev/null
else
  op item create \
    --vault "$VAULT" \
    --category "Secure Note" \
    --title "$ITEM" \
    "${args[@]}" >/dev/null
fi

echo "populated op://$VAULT/$ITEM"
echo "verify with: op read op://$VAULT/$ITEM/kubeadm-token"
