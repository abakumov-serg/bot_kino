#!/usr/bin/env bash
set -Eeuo pipefail

# Run on the VPS. Sets up one public HTTPS endpoint for any number of
# Telegram webhook bot containers.
#
# Registry format (space-separated, one bot per line):
#   <project_name> <webhook_path> <host_port>
#
# Example:
#   bot_kino /bot-kino 127.0.0.1:18081
#   another_bot /another-bot 127.0.0.1:18082

PUBLIC_HOST="${PUBLIC_HOST:-130.162.43.132}"
PUBLIC_PORT="${PUBLIC_PORT:-8443}"
PROXY_PROJECT="${PROXY_PROJECT:-bot_kino_webhook_proxy}"
PROXY_ROOT="${PROXY_ROOT:-/opt/bot_kino-webhook-proxy/current}"
BOT_REGISTRY_FILE="${BOT_REGISTRY_FILE:-${PROXY_ROOT}/webhook-bots.tsv}"

CERT_DIR="${PROXY_ROOT}/secrets"
CERT_FILE="${CERT_DIR}/webhook.crt"
KEY_FILE="${CERT_DIR}/webhook.key"
DEFAULT_BOT_PROJECT="${DEFAULT_BOT_PROJECT:-bot_kino}"
DEFAULT_BOT_PATH="${DEFAULT_BOT_PATH:-/bot-kino}"
DEFAULT_BOT_HOST_PORT="${DEFAULT_BOT_HOST_PORT:-127.0.0.1:18081}"

token_re='^[0-9]{6,}:[A-Za-z0-9_-]{20,}$'

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $1"
    exit 1
  fi
}

normalize_host_port() {
  local value="$1"
  if [[ "${value}" == *:* ]]; then
    printf "%s" "${value}"
  else
    printf "127.0.0.1:%s" "${value}"
  fi
}

upsert_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  mkdir -p "$(dirname "${file}")"
  touch "${file}"

  local tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "${file}"; then
    sed -E "s|^${key}=.*|${key}=${value}|" "${file}" >"${tmp}"
  else
    cat "${file}" >"${tmp}"
    if [[ -s "${tmp}" ]]; then
      printf "\n" >>"${tmp}"
    fi
    printf "%s=%s\n" "${key}" "${value}" >>"${tmp}"
  fi
  mv "${tmp}" "${file}"
}

configure_bot_env_file() {
  local env_file="$1"
  local webhook_path="$2"
  local host_port="$3"

  upsert_env_value "${env_file}" "TELEGRAM_UPDATE_MODE" "webhook"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_URL" "https://${PUBLIC_HOST}:${PUBLIC_PORT}${webhook_path}"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_LISTEN_HOST" "0.0.0.0"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_LISTEN_PORT" "8080"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_PORT" "${host_port}"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_CERT_FILE" "/app/runtime/secrets/webhook.crt"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_KEY_FILE" ""
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_UPLOAD_CERT" "1"
  upsert_env_value "${env_file}" "TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES" "0"
  chmod 600 "${env_file}"
}

copy_cert_to_bot() {
  local project="$1"
  local secrets_dir="/opt/${project}-container/current/runtime/secrets"
  mkdir -p "${secrets_dir}"
  cp "${CERT_FILE}" "${secrets_dir}/webhook.crt"
  chmod 600 "${secrets_dir}/webhook.crt"
}

configure_project_env() {
  local project="$1"
  local webhook_path="$2"
  local host_port="$3"
  local current_dir="/opt/${project}-container/current"
  local secrets_env="${current_dir}/runtime/secrets/.env"
  local staging_env="/home/opc/${project}-src/.env"

  if [[ ! -d "${current_dir}" ]]; then
    echo "Skipping ${project}: ${current_dir} not found yet."
    return
  fi

  configure_bot_env_file "${secrets_env}" "${webhook_path}" "${host_port}"
  ln -sfn "${secrets_env}" "${current_dir}/.env"

  if [[ -d "/home/opc/${project}-src" ]]; then
    configure_bot_env_file "${staging_env}" "${webhook_path}" "${host_port}"
  fi

  copy_cert_to_bot "${project}"
}

read_env_value() {
  local file="$1"
  local key="$2"
  grep -E "^${key}=" "${file}" | tail -1 | cut -d= -f2- || true
}

project_has_valid_token() {
  local project="$1"
  local env_file="/opt/${project}-container/current/runtime/secrets/.env"
  local token
  token="$(read_env_value "${env_file}" "TELEGRAM_BOT_TOKEN")"
  [[ "${token}" =~ ${token_re} ]]
}

start_project_if_ready() {
  local project="$1"
  local current_dir="/opt/${project}-container/current"
  if [[ ! -f "${current_dir}/docker-compose.yml" ]]; then
    echo "Skipping ${project}: docker-compose.yml not found."
    return
  fi

  if project_has_valid_token "${project}"; then
    echo "==> Starting ${project}"
    (cd "${current_dir}" && docker compose -p "${project}" up -d --build --remove-orphans)
  else
    echo "Skipping ${project}: TELEGRAM_BOT_TOKEN is missing or still placeholder."
  fi
}

write_default_registry_if_missing() {
  if [[ -f "${BOT_REGISTRY_FILE}" ]]; then
    return
  fi
  cat >"${BOT_REGISTRY_FILE}" <<EOF
# project_name webhook_path host_port
${DEFAULT_BOT_PROJECT} ${DEFAULT_BOT_PATH} ${DEFAULT_BOT_HOST_PORT}
EOF
}

write_nginx_config_header() {
  cat >"${PROXY_ROOT}/nginx.conf" <<EOF
events {}

http {
    server {
        listen ${PUBLIC_PORT} ssl;
        server_name _;

        ssl_certificate     /etc/nginx/secrets/webhook.crt;
        ssl_certificate_key /etc/nginx/secrets/webhook.key;

        location = /healthz {
            add_header Content-Type text/plain;
            return 200 "ok\n";
        }
EOF
}

append_nginx_location() {
  local webhook_path="$1"
  local host_port="$2"
  local target
  target="$(normalize_host_port "${host_port}")"

  cat >>"${PROXY_ROOT}/nginx.conf" <<EOF

        location = ${webhook_path} {
            proxy_pass http://${target};
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
        }
EOF
}

write_nginx_config_footer() {
  cat >>"${PROXY_ROOT}/nginx.conf" <<EOF
    }
}
EOF
}

require_command docker
require_command openssl
require_command sudo

echo "==> Preparing proxy directory: ${PROXY_ROOT}"
sudo mkdir -p "${PROXY_ROOT}" "${CERT_DIR}"
sudo chown -R "$(id -u):$(id -g)" "$(dirname "${PROXY_ROOT}")"

write_default_registry_if_missing

if [[ ! -f "${CERT_FILE}" || ! -f "${KEY_FILE}" ]]; then
  echo "==> Generating webhook self-signed certificate for ${PUBLIC_HOST}"
  if [[ "${PUBLIC_HOST}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="IP:${PUBLIC_HOST}"
  else
    SAN="DNS:${PUBLIC_HOST}"
  fi
  openssl req -newkey rsa:2048 -sha256 -nodes -x509 -days 365 \
    -keyout "${KEY_FILE}" \
    -out "${CERT_FILE}" \
    -subj "/CN=${PUBLIC_HOST}" \
    -addext "subjectAltName=${SAN}"
  chmod 600 "${CERT_FILE}" "${KEY_FILE}"
else
  echo "==> Reusing existing certificate: ${CERT_FILE}"
fi

echo "==> Writing nginx config from registry: ${BOT_REGISTRY_FILE}"
write_nginx_config_header

configured_projects=()
while read -r project webhook_path host_port _rest; do
  [[ -z "${project}" || "${project}" == \#* ]] && continue
  if [[ -z "${webhook_path:-}" || -z "${host_port:-}" ]]; then
    echo "Skipping bad registry line for project '${project}'."
    continue
  fi
  if [[ "${webhook_path}" != /* ]]; then
    echo "Skipping ${project}: webhook path must start with '/'."
    continue
  fi

  append_nginx_location "${webhook_path}" "${host_port}"
  configure_project_env "${project}" "${webhook_path}" "${host_port}"
  configured_projects+=("${project}")
done <"${BOT_REGISTRY_FILE}"

write_nginx_config_footer

cat >"${PROXY_ROOT}/docker-compose.yml" <<EOF
services:
  webhook-proxy:
    image: nginx:1.27-alpine
    container_name: bot-kino-webhook-proxy
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./secrets:/etc/nginx/secrets:ro
EOF

echo "==> Starting webhook reverse proxy"
(cd "${PROXY_ROOT}" && docker compose -p "${PROXY_PROJECT}" up -d --remove-orphans)

if command -v firewall-cmd >/dev/null 2>&1 && sudo firewall-cmd --state >/dev/null 2>&1; then
  echo "==> Opening firewalld port ${PUBLIC_PORT}/tcp"
  sudo firewall-cmd --permanent --add-port="${PUBLIC_PORT}/tcp"
  sudo firewall-cmd --reload
fi

for project in "${configured_projects[@]}"; do
  start_project_if_ready "${project}"
done

echo "==> Done."
echo "Public health: https://${PUBLIC_HOST}:${PUBLIC_PORT}/healthz"
echo "Registry: ${BOT_REGISTRY_FILE}"
echo "Proxy logs: docker compose -p ${PROXY_PROJECT} -f ${PROXY_ROOT}/docker-compose.yml logs -f --tail=120"
