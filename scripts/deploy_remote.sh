#!/usr/bin/env bash
set -Eeuo pipefail

# Local helper script (run on Mac/Linux) that:
# 1) syncs project files to VPS staging directory
# 2) optionally uploads local .env to staging
# 3) connects via SSH and runs server-side deploy script
#
# Usage:
#   ./scripts/deploy_remote.sh [project-name] [--no-up] [--no-env] [--logs]
#
# Env overrides:
#   REMOTE_USER (default: opc)
#   REMOTE_HOST (default: 130.162.43.132)
#   SSH_KEY     (default: ~/Downloads/ssh-key-2026-04-28.key)
#   REMOTE_STAGING (default: /home/<REMOTE_USER>/<project-name>-src)

usage() {
  echo "Usage: $0 [project-name] [--no-up] [--no-env] [--logs]"
  echo
  echo "Options:"
  echo "  --no-up   Sync only; skip docker compose up on server"
  echo "  --no-env  Do not upload local .env to staging"
  echo "  --logs    Attach to container logs after deploy"
}

PROJECT_NAME="bot_kino"
NO_UP=""
COPY_ENV=1
TAIL_LOGS=0
PROJECT_SET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --no-up)
      NO_UP="--no-up"
      ;;
    --no-env)
      COPY_ENV=0
      ;;
    --logs)
      TAIL_LOGS=1
      ;;
    -*)
      echo "ERROR: unknown option: $1"
      usage
      exit 1
      ;;
    *)
      if [[ "${PROJECT_SET}" -eq 0 ]]; then
        PROJECT_NAME="$1"
        PROJECT_SET=1
      else
        echo "ERROR: unexpected argument: $1"
        usage
        exit 1
      fi
      ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REMOTE_USER="${REMOTE_USER:-opc}"
REMOTE_HOST="${REMOTE_HOST:-130.162.43.132}"
SSH_KEY="${SSH_KEY:-$HOME/Downloads/ssh-key-2026-04-28.key}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_STAGING="${REMOTE_STAGING:-/home/${REMOTE_USER}/${PROJECT_NAME}-src}"
REMOTE_COMPOSE="/opt/${PROJECT_NAME}-container/current/docker-compose.yml"
SSH_RSH="ssh -i ${SSH_KEY} -o IdentitiesOnly=yes"

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "ERROR: SSH key not found: ${SSH_KEY}"
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ERROR: ssh is required."
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "ERROR: rsync is required."
  exit 1
fi

echo "==> Preparing remote staging: ${REMOTE_STAGING}"
ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes "${REMOTE}" "mkdir -p '${REMOTE_STAGING}'"

echo "==> Syncing project files to ${REMOTE}:${REMOTE_STAGING}"
rsync -az --delete \
  -e "${SSH_RSH}" \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude ".DS_Store" \
  --exclude ".env" \
  --exclude "runtime/" \
  "${LOCAL_ROOT}/" "${REMOTE}:${REMOTE_STAGING}/"

LOCAL_ENV_FILE="${LOCAL_ROOT}/.env"
if [[ "${COPY_ENV}" -eq 1 && -f "${LOCAL_ENV_FILE}" ]]; then
  echo "==> Uploading local .env to staging"
  scp -i "${SSH_KEY}" -o IdentitiesOnly=yes "${LOCAL_ENV_FILE}" "${REMOTE}:${REMOTE_STAGING}/.env" >/dev/null
elif [[ "${COPY_ENV}" -eq 1 ]]; then
  echo "==> Local .env not found, skipping .env upload"
fi

echo "==> Running remote deploy script"
if [[ -n "${NO_UP}" ]]; then
  ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes "${REMOTE}" "cd '${REMOTE_STAGING}' && chmod +x ./scripts/deploy_project.sh && ./scripts/deploy_project.sh '${PROJECT_NAME}' --no-up"
else
  ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes "${REMOTE}" "cd '${REMOTE_STAGING}' && chmod +x ./scripts/deploy_project.sh && ./scripts/deploy_project.sh '${PROJECT_NAME}'"
fi

if [[ "${TAIL_LOGS}" -eq 1 ]]; then
  echo "==> Attaching logs"
  ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes -t "${REMOTE}" "docker compose -f '${REMOTE_COMPOSE}' logs -f --tail=120"
else
  echo "==> Done."
  echo "Logs: ssh -i '${SSH_KEY}' ${REMOTE} \"docker compose -f '${REMOTE_COMPOSE}' logs -f --tail=120\""
fi
