# Multikino Telegram Bot

Telegram-бот для `Multikino Warszawa Młociny`, який:

- показує фільми на найближчі 7 днів;
- відкидає дитячі фільми;
- окремо групує сучасні фільми і ретро (за десятиліттями: 2000-ті, 1990-ті тощо).
- у звіті виділяє назву фільму і показує жанр.

## 1) Встановлення

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Налаштування

1. Скопіюй файл `.env.example` у `.env` (або просто вистав змінні середовища).
2. Вкажи `TELEGRAM_BOT_TOKEN` (або просто запусти бота і встав токен один раз у консоль - він сам збереже у `.env`).
3. (Опційно) Додай ключі `TMDB_API_KEY` і `OMDB_API_KEY`, щоб бот показував рейтинги.
4. (Опційно) `BOT_LOCALE=uk|pl|en` для базової мови інтерфейсу бота.
5. (Опційно) `BOT_LOCALE_AUTO=1` (за замовчуванням) — автопідбір мови за `Telegram language_code` користувача (`uk|pl|en`).
6. Якщо треба жорстко одна мова для всіх, постав `BOT_LOCALE_AUTO=0`.
7. (Опційно) `BOT_CINEMA_LABEL=...` для свого лейблу кінотеатру в заголовку звіту.
8. Для Oracle VPS можна задати `MULTIKINO_CINEMA_ID=0040`, щоб обійти 403 на HTML-сторінці.
9. Якщо Multikino блокує ваш VPS IP (403 навіть на showings API), задай `MULTIKINO_PROXY_URL=http://user:pass@host:port`.

Приклад:

```bash
export TELEGRAM_BOT_TOKEN='123456789:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
export MULTIKINO_CINEMA_SLUG='warszawa-mlociny'
```

## 3) Швидка перевірка без Telegram

```bash
python3 bot.py --print-week
```

## 4) Запуск Telegram-бота

```bash
python3 bot.py
```

За замовчуванням бот працює в `auto`-режимі:

- якщо `TELEGRAM_WEBHOOK_URL` порожній, використовується старий polling через `getUpdates`;
- якщо `TELEGRAM_WEBHOOK_URL` заданий, бот сам реєструє webhook через `setWebhook` і Telegram надсилає updates на твій сервер.

Команди в Telegram:

- `/week` — звіт на 7 днів (із сеансами);
- `/week_l` — тільки перелік фільмів на 7 днів (без сеансів);
- `/today` — звіт на сьогодні (із сеансами);
- `/today_l` — тільки перелік фільмів на сьогодні (без сеансів);
- `/tomorrow` — звіт на завтра (із сеансами);
- `/tomorrow_l` — тільки перелік фільмів на завтра (без сеансів);
- `/commands` — список доступних команд;
- `/help` — довідка.

## 5) Webhook на VPS

Telegram webhook потребує публічний `HTTPS` URL. Підтримувані Telegram порти для webhook: `443`, `80`, `88`, `8443`.

### Варіант A: reverse proxy з доменом

Це найзручніший варіант, якщо є домен і Caddy/Nginx робить HTTPS:

```bash
TELEGRAM_UPDATE_MODE=webhook
TELEGRAM_WEBHOOK_URL=https://kino.example.com/telegram/webhook
TELEGRAM_WEBHOOK_LISTEN_HOST=0.0.0.0
TELEGRAM_WEBHOOK_LISTEN_PORT=8080
TELEGRAM_WEBHOOK_PORT=8080
```

Reverse proxy має прокидати запити на контейнерний порт `8080`.

### Варіант B: напряму на зовнішній IP і порт 8443

Якщо домену немає, можна підняти прямий HTTPS у контейнері та передати Telegram self-signed сертифікат.

На сервері створи сертифікат:

```bash
cd /opt/bot_kino-container/current
mkdir -p runtime/secrets
openssl req -newkey rsa:2048 -sha256 -nodes -x509 -days 365 \
  -keyout runtime/secrets/webhook.key \
  -out runtime/secrets/webhook.crt \
  -subj "/CN=130.162.43.132" \
  -addext "subjectAltName=IP:130.162.43.132"
chmod 600 runtime/secrets/webhook.key runtime/secrets/webhook.crt
```

У `.env`:

```bash
TELEGRAM_UPDATE_MODE=webhook
TELEGRAM_WEBHOOK_URL=https://130.162.43.132:8443
TELEGRAM_WEBHOOK_LISTEN_PORT=8443
TELEGRAM_WEBHOOK_PORT=8443
TELEGRAM_WEBHOOK_CERT_FILE=/app/runtime/secrets/webhook.crt
TELEGRAM_WEBHOOK_KEY_FILE=/app/runtime/secrets/webhook.key
TELEGRAM_WEBHOOK_UPLOAD_CERT=1
```

Також відкрий порт `8443/tcp` у firewall на сервері та в ingress rules Oracle Cloud.

```bash
sudo firewall-cmd --permanent --add-port=8443/tcp
sudo firewall-cmd --reload
```

Після зміни `.env`:

```bash
docker compose -f /opt/bot_kino-container/current/docker-compose.yml up -d --build --force-recreate
docker compose -f /opt/bot_kino-container/current/docker-compose.yml logs -f --tail=120
```

Перевірка локального health endpoint:

```bash
curl -k https://130.162.43.132:8443/healthz
```

### Багато ботів на одному IP і порту

Можна підключити 2-го, 3-го або 10-го Telegram-бота до однієї публічної адреси. У всіх буде один host/port, але різні webhook paths:

```text
https://130.162.43.132:8443/bot-kino
https://130.162.43.132:8443/tasks-bot
https://130.162.43.132:8443/another-bot
```

Напряму кілька Docker-контейнерів не можуть одночасно зайняти один host-порт `8443`, тому використовується один reverse proxy. Самі боти слухають різні локальні порти, наприклад `18081`, `18082`, `18083`.

На сервері є універсальний setup-скрипт: [scripts/setup_webhook_proxy_server.sh](/Users/fisha/Projects/kino/scripts/setup_webhook_proxy_server.sh). Він читає registry-файл:

```text
/opt/bot_kino-webhook-proxy/current/webhook-bots.tsv
```

Формат registry:

```text
# project_name webhook_path host_port
bot_kino /bot-kino 127.0.0.1:18081
tasks_bot /tasks-bot 127.0.0.1:18082
another_bot /another-bot 127.0.0.1:18083
```

Для кожного рядка скрипт:

- додає route у nginx reverse proxy;
- ставить `TELEGRAM_UPDATE_MODE=webhook`;
- ставить правильний `TELEGRAM_WEBHOOK_URL`;
- копіює public certificate у `runtime/secrets/webhook.crt`;
- запускає контейнер тільки якщо в `.env` є валідний `TELEGRAM_BOT_TOKEN`.

Перший запуск для поточного бота:

```bash
cd /home/opc/bot_kino-src
bash ./scripts/setup_webhook_proxy_server.sh
```

Або з локального Mac після синхронізації коду:

```bash
bash /Users/fisha/Projects/kino/scripts/setup_webhook_proxy_remote.sh
```

Щоб додати ще одного бота:

```bash
bash /Users/fisha/Projects/kino/scripts/deploy_remote.sh tasks_bot --no-env --no-up
```

Потім на сервері додай рядок:

```bash
echo "tasks_bot /tasks-bot 127.0.0.1:18082" >> /opt/bot_kino-webhook-proxy/current/webhook-bots.tsv
```

Впиши token другого бота в:

```text
/opt/tasks_bot-container/current/runtime/secrets/.env
```

І перезапусти proxy setup:

```bash
cd /home/opc/bot_kino-src
bash ./scripts/setup_webhook_proxy_server.sh
```

## 6) Деплой у Docker (Linux VPS)

На сервері в папці проєкту:

```bash
cp .env.example .env
```

Відкрий `.env` і впиши свій `TELEGRAM_BOT_TOKEN`.

Потім запуск:

```bash
docker compose up -d --build
```

Корисні команди:

```bash
docker compose logs -f
docker compose restart
docker compose down
```

Після оновлення коду:

```bash
docker compose up -d --build
```

### Oracle Linux 9

Встановлення Docker Engine + Compose plugin:

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Щоб запускати Docker без `sudo`:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Деплой під твою структуру (`bot_kino`)

У репо є скрипт: [scripts/deploy_project.sh](/Users/fisha/Projects/kino/scripts/deploy_project.sh)

Він робить:
- синхронізацію з `/home/opc/<project-name>-src` у `/opt/<project-name>-container/current`;
- створення runtime-папок;
- якщо існує `/home/opc/<project-name>-src/.env`, копіює його в `runtime/secrets/.env`;
- якщо `.env` у staging немає і secrets-файла ще немає, створює його з `.env.example`;
- запуск `docker compose up -d --build`.

Запуск на сервері:

```bash
cd /home/opc/bot_kino-src
./scripts/deploy_project.sh bot_kino
```

Локальний one-click скрипт (з Mac/Linux): [scripts/deploy_remote.sh](/Users/fisha/Projects/kino/scripts/deploy_remote.sh)

Він:
- копіює код у `/home/opc/bot_kino-src`;
- (за замовчуванням) копіює локальний `.env` у staging;
- підключається по SSH і запускає `./scripts/deploy_project.sh bot_kino` на сервері.

Запуск:

```bash
bash /Users/fisha/Projects/kino/scripts/deploy_remote.sh
```

Опції:

```bash
bash /Users/fisha/Projects/kino/scripts/deploy_remote.sh --no-up
bash /Users/fisha/Projects/kino/scripts/deploy_remote.sh --no-env
bash /Users/fisha/Projects/kino/scripts/deploy_remote.sh --logs
```

Або без запуску контейнера:

```bash
./scripts/deploy_project.sh bot_kino --no-up
```

Якщо хочеш закинути `.env` з локального Mac у staging на сервері:

```bash
scp -i ~/Downloads/ssh-key-2026-04-28.key /Users/fisha/Projects/kino/.env opc@130.162.43.132:/home/opc/bot_kino-src/.env
```

Після цього звичайний деплой автоматично оновить secrets-файл:

```bash
cd /home/opc/bot_kino-src
./scripts/deploy_project.sh bot_kino
```

## Нотатки

- Бот використовує публічні endpoint-и `multikino.pl` і автоматично отримує службовий токен доступу.
- Фільтрація дитячих фільмів робиться за жанрами/атрибутами фільму і ключовими словами в назві.
- Рейтинги TMDb/OMDb показуються лише якщо задані `TMDB_API_KEY` / `OMDB_API_KEY`.
- `/commands` і `/help` формуються з одного джерела (без копіпасти в коді).
