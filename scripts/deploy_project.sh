#!/usr/bin/env bash
set -Eeuo pipefail

# Deploy script for structured layout:
# - staging source: /home/opc/<project-name>-src
# - deployed code : /opt/<project-name>-container/current
# - runtime data  : /opt/<project-name>-container/current/runtime/app-data
# - secrets       : /opt/<project-name>-container/current/runtime/secrets
#
# Usage:
#   ./scripts/deploy_project.sh [project-name] [--no-up]
#
# Example:
#   ./scripts/deploy_project.sh bot_kino

PROJECT_NAME="${1:-bot_kino}"
NO_UP="${2:-}"

STAGING_SRC="/home/opc/${PROJECT_NAME}-src"
PROJECT_ROOT="/opt/${PROJECT_NAME}-container"
CURRENT_DIR="${PROJECT_ROOT}/current"
RUNTIME_DIR="${CURRENT_DIR}/runtime"
APP_DATA_DIR="${RUNTIME_DIR}/app-data"
SECRETS_DIR="${RUNTIME_DIR}/secrets"
SECRETS_ENV_FILE="${SECRETS_DIR}/.env"
LINKED_ENV_FILE="${CURRENT_DIR}/.env"

if [[ ! -d "${STAGING_SRC}" ]]; then
  echo "ERROR: staging directory not found: ${STAGING_SRC}"
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "ERROR: rsync is required."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required."
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "ERROR: sudo is required for writing /opt paths."
  exit 1
fi

echo "==> Preparing directories"
sudo mkdir -p "${CURRENT_DIR}" "${APP_DATA_DIR}" "${SECRETS_DIR}"
sudo chown -R "$(id -u):$(id -g)" "${PROJECT_ROOT}"

echo "==> Syncing code from ${STAGING_SRC} to ${CURRENT_DIR}"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude ".env" \
  --exclude "runtime/" \
  "${STAGING_SRC}/" "${CURRENT_DIR}/"

echo "==> Ensuring runtime dirs"
mkdir -p "${APP_DATA_DIR}" "${SECRETS_DIR}"

if [[ ! -f "${SECRETS_ENV_FILE}" ]]; then
  if [[ -f "${CURRENT_DIR}/.env.example" ]]; then
    cp "${CURRENT_DIR}/.env.example" "${SECRETS_ENV_FILE}"
  else
    touch "${SECRETS_ENV_FILE}"
  fi
  chmod 600 "${SECRETS_ENV_FILE}"
  echo "Created secrets env file: ${SECRETS_ENV_FILE}"
fi

ln -sfn "${SECRETS_ENV_FILE}" "${LINKED_ENV_FILE}"

if [[ "${NO_UP}" == "--no-up" ]]; then
  echo "==> Skipping docker compose up (--no-up)"
  echo "Done."
  exit 0
fi

echo "==> Starting containers"
cd "${CURRENT_DIR}"
docker compose up -d --build --remove-orphans

echo "==> Done."
echo "Project: ${PROJECT_NAME}"
echo "Code:    ${CURRENT_DIR}"
echo "Data:    ${APP_DATA_DIR}"
echo "Secrets: ${SECRETS_ENV_FILE}"
echo "Logs:    docker compose -f ${CURRENT_DIR}/docker-compose.yml logs -f"
