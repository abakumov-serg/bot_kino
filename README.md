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

Команди в Telegram:

- `/week` — звіт на 7 днів (із сеансами);
- `/week_l` — тільки перелік фільмів на 7 днів (без сеансів);
- `/today` — звіт на сьогодні (із сеансами);
- `/today_l` — тільки перелік фільмів на сьогодні (без сеансів);
- `/tomorrow` — звіт на завтра (із сеансами);
- `/tomorrow_l` — тільки перелік фільмів на завтра (без сеансів);
- `/commands` — список доступних команд;
- `/help` — довідка.

## 5) Деплой у Docker (Linux VPS)

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
- створення secrets-файла `.env` у `runtime/secrets`;
- запуск `docker compose up -d --build`.

Запуск на сервері:

```bash
cd /home/opc/bot_kino-src
./scripts/deploy_project.sh bot_kino
```

Або без запуску контейнера:

```bash
./scripts/deploy_project.sh bot_kino --no-up
```

## Нотатки

- Бот використовує публічні endpoint-и `multikino.pl` і автоматично отримує службовий токен доступу.
- Фільтрація дитячих фільмів робиться за жанрами/атрибутами фільму і ключовими словами в назві.
- Рейтинги TMDb/OMDb показуються лише якщо задані `TMDB_API_KEY` / `OMDB_API_KEY`.
