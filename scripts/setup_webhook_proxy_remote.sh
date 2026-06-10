#!/usr/bin/env bash
set -Eeuo pipefail

# Local helper (run on Mac/Linux). It runs setup_webhook_proxy_server.sh on VPS.
#
# Env overrides:
#   REMOTE_USER    (default: opc)
#   REMOTE_HOST    (default: 130.162.43.132)
#   SSH_KEY        (default: ~/Downloads/ssh-key-2026-04-28.key)
#   REMOTE_STAGING (default: /home/<REMOTE_USER>/bot_kino-src)
#   PUBLIC_HOST    (default: REMOTE_HOST)
#   PUBLIC_PORT    (default: 8443)

REMOTE_USER="${REMOTE_USER:-opc}"
REMOTE_HOST="${REMOTE_HOST:-130.162.43.132}"
SSH_KEY="${SSH_KEY:-$HOME/Downloads/ssh-key-2026-04-28.key}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_STAGING="${REMOTE_STAGING:-/home/${REMOTE_USER}/bot_kino-src}"
PUBLIC_HOST="${PUBLIC_HOST:-${REMOTE_HOST}}"
PUBLIC_PORT="${PUBLIC_PORT:-8443}"

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "ERROR: SSH key not found: ${SSH_KEY}"
  exit 1
fi

ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes "${REMOTE}" \
  "cd '${REMOTE_STAGING}' && chmod +x ./scripts/setup_webhook_proxy_server.sh && PUBLIC_HOST='${PUBLIC_HOST}' PUBLIC_PORT='${PUBLIC_PORT}' ./scripts/setup_webhook_proxy_server.sh"
