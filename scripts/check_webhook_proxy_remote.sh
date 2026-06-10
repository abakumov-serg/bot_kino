#!/usr/bin/env bash
set -Eeuo pipefail

# Local helper (run on Mac/Linux). Checks webhook proxy/container status on VPS
# without printing secrets.

REMOTE_USER="${REMOTE_USER:-opc}"
REMOTE_HOST="${REMOTE_HOST:-130.162.43.132}"
SSH_KEY="${SSH_KEY:-$HOME/Downloads/ssh-key-2026-04-28.key}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
PUBLIC_PORT="${PUBLIC_PORT:-8443}"
BOT_PROJECT="${BOT_PROJECT:-bot_kino}"
PROXY_PROJECT="${PROXY_PROJECT:-bot_kino_webhook_proxy}"
PROXY_COMPOSE="${PROXY_COMPOSE:-/opt/bot_kino-webhook-proxy/current/docker-compose.yml}"
BOT_COMPOSE="${BOT_COMPOSE:-/opt/${BOT_PROJECT}-container/current/docker-compose.yml}"

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "ERROR: SSH key not found: ${SSH_KEY}"
  exit 1
fi

ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes "${REMOTE}" "
  set -e
  echo '== docker ps =='
  docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}' | grep -E 'webhook-proxy|${BOT_PROJECT}|NAMES' || true
  echo
  echo '== local health =='
  curl -sk --max-time 5 https://127.0.0.1:${PUBLIC_PORT}/healthz || true
  echo
  echo '== public ip from server =='
  curl -sS --max-time 5 https://api.ipify.org || true
  echo
  echo
  echo '== listening sockets =='
  sudo ss -lntp | grep -E ':${PUBLIC_PORT}|:18081|:18082|:8080' || true
  echo
  echo '== proxy logs =='
  docker compose -p '${PROXY_PROJECT}' -f '${PROXY_COMPOSE}' logs --tail=40
  echo
  echo '== bot logs =='
  docker compose -p '${BOT_PROJECT}' -f '${BOT_COMPOSE}' logs --tail=80
"
