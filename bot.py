#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import re
import ssl
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import urllib3

BASE_URL = "https://www.multikino.pl"
DEFAULT_CINEMA_SLUG = "warszawa-mlociny"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

WEEKDAY_LABELS = {
    "uk": {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Нд"},
    "pl": {0: "Pn", 1: "Wt", 2: "Śr", 3: "Cz", 4: "Pt", 5: "Sb", 6: "Nd"},
    "en": {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"},
}

KIDS_GENRE_KEYWORDS = {
    "familijny",
    "dla dzieci",
    "dzieci",
    "bajka",
}
KIDS_ATTRIBUTE_KEYWORDS = {
    "familijny",
    "dla dzieci",
    "dzieci",
}
KIDS_TITLE_KEYWORDS = (
    "tom i jerry",
    "disney junior",
    "bajka",
    "dzieci",
    "skarpetek",
    "kurozajac",
    "peppa",
    "psi patrol",
)
TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
YEAR_IN_TEXT_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
SEQUEL_TEXT_HINTS = (
    "kontynuac",
    "sequel",
    "powrac",
    "druga czę",
    "druga czesc",
    "część 2",
    "czesc 2",
    "part 2",
)
MOVIE_MARK = "🔹"
GENRE_MARK = "🔸"
SESSIONS_MARK = "▶️"
SPECIAL_PRADA_NOTE = "🟥 Герасимова, може сюди сходимо?"
RATINGS_MARK = "⭐"
FILM_SEPARATOR = "────────────"
REPORT_COMMANDS: dict[str, tuple[int, bool, int]] = {
    "/today": (1, False, 0),
    "/today_l": (1, True, 0),
    "/tomorrow": (1, False, 1),
    "/tomorrow_l": (1, True, 1),
    "/week": (7, False, 0),
    "/week_l": (7, True, 0),
}
SUPPORTED_LOCALES: tuple[str, ...] = ("uk", "pl", "en")
COMMAND_SPECS: tuple[tuple[str, str], ...] = (
    ("week", "cmd_week"),
    ("week_l", "cmd_week_l"),
    ("today", "cmd_today"),
    ("today_l", "cmd_today_l"),
    ("tomorrow", "cmd_tomorrow"),
    ("tomorrow_l", "cmd_tomorrow_l"),
    ("commands", "cmd_commands"),
    ("help", "cmd_help"),
)
KNOWN_CINEMA_LABELS = {
    "warszawa-mlociny": "Warszawa Młociny",
}
KNOWN_CINEMA_IDS = {
    "warszawa-mlociny": "0040",
}
WEBHOOK_ALLOWED_UPDATES = ["message"]
LOCALE_TEXTS: dict[str, dict[str, str]] = {
    "uk": {
        "commands_title": "Доступні команди",
        "cmd_week": "7 днів, із сеансами",
        "cmd_week_l": "7 днів, без сеансів",
        "cmd_today": "Сьогодні, із сеансами",
        "cmd_today_l": "Сьогодні, без сеансів",
        "cmd_tomorrow": "Завтра, із сеансами",
        "cmd_tomorrow_l": "Завтра, без сеансів",
        "cmd_commands": "Список доступних команд",
        "cmd_help": "Підказка",
        "start_intro": "Привіт. Я бот для {cinema_label}.",
        "unknown_command": "Не зрозумів команду.",
        "schedule_fetch_failed": "Не вдалося отримати розклад. Спробуй ще раз трохи пізніше.",
        "multikino_ip_blocked": (
            "Multikino блокує запити з цього сервера (403). "
            "Додай MULTIKINO_PROXY_URL у .env або зміни egress IP."
        ),
        "cinema_label": "Кіно",
        "period_label": "Період",
        "kids_filtered": "Дитячі фільми відфільтровано.",
        "list_only_format": "Формат: тільки перелік фільмів (без сеансів).",
        "ratings_enabled": "Рейтинги: увімкнено (TMDb/OMDb).",
        "ratings_disabled": "Рейтинги: вимкнено. Додай TMDB_API_KEY і OMDB_API_KEY у .env.",
        "no_sessions": "Немає сеансів за обраними умовами.",
        "no_movies": "Немає фільмів за обраними умовами.",
        "modern_section": "Сучасні ({year}+):",
        "retro_section": "Ретро за десятиліттями:",
        "unknown_year_section": "Без року релізу:",
        "no_items": "- Немає",
        "genre_label": "Жанр",
        "unknown_genre": "невідомо",
        "decade_suffix": "-ті",
        "help_title": "Довідка",
        "help_about": (
            "Цей бот показує розклад Multikino, відфільтровує дитячі фільми, "
            "ділить фільми на сучасні та ретро і може показувати рейтинги TMDb/OMDb."
        ),
        "help_commands_hint": "Список команд: /commands",
        "locale_current": "Поточна локалізація: {locale_name} ({locale_code})",
        "locale_available": "Доступні локалі: {locales}",
        "locale_hint": "Адмін може змінити мову через BOT_LOCALE=uk|pl|en у .env.",
        "lang_name_uk": "українська",
        "lang_name_pl": "польська",
        "lang_name_en": "англійська",
    },
    "pl": {
        "commands_title": "Dostępne komendy",
        "cmd_week": "7 dni, z seansami",
        "cmd_week_l": "7 dni, bez seansów",
        "cmd_today": "Dzisiaj, z seansami",
        "cmd_today_l": "Dzisiaj, bez seansów",
        "cmd_tomorrow": "Jutro, z seansami",
        "cmd_tomorrow_l": "Jutro, bez seansów",
        "cmd_commands": "Lista komend",
        "cmd_help": "Pomoc",
        "start_intro": "Cześć. Jestem botem dla {cinema_label}.",
        "unknown_command": "Nie rozumiem komendy.",
        "schedule_fetch_failed": "Nie udało się pobrać repertuaru. Spróbuj ponownie trochę później.",
        "multikino_ip_blocked": (
            "Multikino blokuje zapytania z tego serwera (403). "
            "Dodaj MULTIKINO_PROXY_URL do .env albo zmień adres egress IP."
        ),
        "cinema_label": "Kino",
        "period_label": "Okres",
        "kids_filtered": "Filmy dziecięce odfiltrowane.",
        "list_only_format": "Tryb: tylko lista filmów (bez seansów).",
        "ratings_enabled": "Oceny: włączone (TMDb/OMDb).",
        "ratings_disabled": "Oceny: wyłączone. Dodaj TMDB_API_KEY i OMDB_API_KEY w .env.",
        "no_sessions": "Brak seansów dla wybranych warunków.",
        "no_movies": "Brak filmów dla wybranych warunków.",
        "modern_section": "Współczesne ({year}+):",
        "retro_section": "Retro według dekad:",
        "unknown_year_section": "Bez roku premiery:",
        "no_items": "- Brak",
        "genre_label": "Gatunek",
        "unknown_genre": "nieznany",
        "decade_suffix": "-te",
        "help_title": "Pomoc",
        "help_about": (
            "Ten bot pokazuje repertuar Multikino, filtruje filmy dziecięce, "
            "dzieli filmy na współczesne i retro oraz może pokazywać oceny TMDb/OMDb."
        ),
        "help_commands_hint": "Lista komend: /commands",
        "locale_current": "Bieżąca lokalizacja: {locale_name} ({locale_code})",
        "locale_available": "Dostępne języki: {locales}",
        "locale_hint": "Administrator może zmienić język przez BOT_LOCALE=uk|pl|en w .env.",
        "lang_name_uk": "ukraiński",
        "lang_name_pl": "polski",
        "lang_name_en": "angielski",
    },
    "en": {
        "commands_title": "Available commands",
        "cmd_week": "7 days, with sessions",
        "cmd_week_l": "7 days, no sessions",
        "cmd_today": "Today, with sessions",
        "cmd_today_l": "Today, no sessions",
        "cmd_tomorrow": "Tomorrow, with sessions",
        "cmd_tomorrow_l": "Tomorrow, no sessions",
        "cmd_commands": "Command list",
        "cmd_help": "Help",
        "start_intro": "Hi. I'm a bot for {cinema_label}.",
        "unknown_command": "Unknown command.",
        "schedule_fetch_failed": "Failed to fetch schedule. Please try again later.",
        "multikino_ip_blocked": (
            "Multikino blocks requests from this server (403). "
            "Set MULTIKINO_PROXY_URL in .env or change egress IP."
        ),
        "cinema_label": "Cinema",
        "period_label": "Period",
        "kids_filtered": "Kids movies filtered out.",
        "list_only_format": "Mode: film list only (no sessions).",
        "ratings_enabled": "Ratings: enabled (TMDb/OMDb).",
        "ratings_disabled": "Ratings: disabled. Add TMDB_API_KEY and OMDB_API_KEY to .env.",
        "no_sessions": "No sessions for selected criteria.",
        "no_movies": "No movies for selected criteria.",
        "modern_section": "Modern ({year}+):",
        "retro_section": "Retro by decades:",
        "unknown_year_section": "Without release year:",
        "no_items": "- None",
        "genre_label": "Genre",
        "unknown_genre": "unknown",
        "decade_suffix": "s",
        "help_title": "Help",
        "help_about": (
            "This bot shows Multikino schedule, filters kids movies, splits films into modern and retro, "
            "and can show TMDb/OMDb ratings."
        ),
        "help_commands_hint": "Command list: /commands",
        "locale_current": "Current locale: {locale_name} ({locale_code})",
        "locale_available": "Available locales: {locales}",
        "locale_hint": "Admin can change language via BOT_LOCALE=uk|pl|en in .env.",
        "lang_name_uk": "Ukrainian",
        "lang_name_pl": "Polish",
        "lang_name_en": "English",
    },
}


def normalize_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def resolve_locale(raw_locale: str) -> str:
    detected = detect_supported_locale(raw_locale)
    if detected:
        return detected
    return "uk"


def detect_supported_locale(raw_locale: str) -> str:
    locale = normalize_text(raw_locale).replace("_", "-")
    # Explicit preference: route Russian locale users to Ukrainian.
    if locale.startswith("ru"):
        return "uk"
    for code in SUPPORTED_LOCALES:
        if locale.startswith(code):
            return code
    return ""


def locale_text(locale: str) -> dict[str, str]:
    return LOCALE_TEXTS.get(locale, LOCALE_TEXTS["uk"])


def weekday_labels(locale: str) -> dict[int, str]:
    return WEEKDAY_LABELS.get(locale, WEEKDAY_LABELS["uk"])


def build_bot_commands(locale: str) -> list[dict[str, str]]:
    texts = locale_text(locale)
    return [{"command": command, "description": texts[text_key]} for command, text_key in COMMAND_SPECS]


def build_commands_text(locale: str) -> str:
    texts = locale_text(locale)
    lines = [f"{texts['commands_title']}:"]
    for command, text_key in COMMAND_SPECS:
        lines.append(f"/{command} - {texts[text_key]}")
    return "\n".join(lines)


def build_help_text(locale: str, current_locale: str) -> str:
    texts = locale_text(locale)
    locale_parts = []
    for code in SUPPORTED_LOCALES:
        locale_name = texts.get(f"lang_name_{code}", code)
        locale_parts.append(f"<code>{code}</code> ({locale_name})")
    locales_text = ", ".join(locale_parts)
    current_name = texts.get(f"lang_name_{current_locale}", current_locale)

    return (
        f"<b>{texts['help_title']}</b>\n"
        f"{texts['help_about']}\n\n"
        f"{texts['help_commands_hint']}\n\n"
        f"{texts['locale_current'].format(locale_name=current_name, locale_code=current_locale)}\n"
        f"{texts['locale_available'].format(locales=locales_text)}\n"
        f"{texts['locale_hint']}"
    )


def resolve_cinema_label(cinema_slug: str) -> str:
    explicit = os.getenv("BOT_CINEMA_LABEL", "").strip()
    if explicit:
        return explicit

    known = KNOWN_CINEMA_LABELS.get(cinema_slug)
    if known:
        return known

    humanized = " ".join(part.capitalize() for part in cinema_slug.replace("-", " ").split())
    return humanized or "Multikino"


def read_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def read_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = normalize_text(value)
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def load_dotenv_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, value)


def upsert_dotenv_value(dotenv_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    if dotenv_path.exists():
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()

    updated: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith(f"{key}="):
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(raw_line)

    if not found:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"{key}={value}")

    dotenv_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def resolve_telegram_token(dotenv_path: Path) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token

    if os.isatty(0):
        print("TELEGRAM_BOT_TOKEN не знайдено.")
        entered = input("Встав токен бота (або Enter для скасування): ").strip()
        if entered:
            if not TOKEN_RE.match(entered):
                raise RuntimeError("Схоже, це не валідний Telegram bot token.")
            upsert_dotenv_value(dotenv_path, "TELEGRAM_BOT_TOKEN", entered)
            os.environ["TELEGRAM_BOT_TOKEN"] = entered
            print(f"Токен збережено у {dotenv_path}")
            return entered

    raise RuntimeError(
        "Не знайдено TELEGRAM_BOT_TOKEN. Додай його в .env або змінні середовища."
    )


@dataclass
class FilmMetadata:
    film_id: str
    title: str
    release_year: int | None
    original_title: str = ""
    synopsis_short: str = ""
    genres: set[str] = field(default_factory=set)
    attributes: set[str] = field(default_factory=set)


@dataclass
class FilmRatings:
    tmdb_vote_average: float | None = None
    tmdb_vote_count: int | None = None
    omdb_imdb_rating: str = ""
    omdb_metascore: str = ""
    omdb_rotten_tomatoes: str = ""
    omdb_year: int | None = None
    omdb_genres: tuple[str, ...] = ()

    def has_any(self) -> bool:
        return (
            self.tmdb_vote_average is not None
            or bool(self.omdb_imdb_rating)
            or bool(self.omdb_metascore)
            or bool(self.omdb_rotten_tomatoes)
        )


@dataclass
class FilmSchedule:
    film_id: str
    title: str
    release_year: int | None
    genres: tuple[str, ...] = ()
    ratings: FilmRatings = field(default_factory=FilmRatings)
    sessions_by_date: dict[date, list[str]] = field(default_factory=dict)

    def add_sessions(self, day: date, times: list[str]) -> None:
        bucket = self.sessions_by_date.setdefault(day, [])
        bucket.extend(times)
        bucket.sort()
        self.sessions_by_date[day] = sorted(set(bucket))


class MultikinoClient:
    def __init__(
        self,
        session: requests.Session,
        cinema_slug: str,
        base_url: str = BASE_URL,
        cinema_id_override: str | None = None,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.cinema_slug = cinema_slug
        self.cinema_id_override = (cinema_id_override or "").strip() or None
        self.cinema_id: str | None = None
        self.build_id: str | None = None
        self._auth_ready = False
        self._film_meta_cache: dict[str, FilmMetadata] = {}

    def initialize(self) -> None:
        if self.cinema_id_override:
            self.cinema_id = self.cinema_id_override
            logging.info(
                "Використовую MULTIKINO_CINEMA_ID=%s для '%s'",
                self.cinema_id,
                self.cinema_slug,
            )

        repertuar_url = f"{self.base_url}/repertuar/{self.cinema_slug}/teraz-gramy"
        try:
            response = self.session.get(repertuar_url, timeout=30)
            response.raise_for_status()
            match = NEXT_DATA_RE.search(response.text)
            if match:
                payload = json.loads(match.group(1))
                self.build_id = payload.get("buildId")
                self.cinema_id = (
                    payload.get("props", {})
                    .get("pageProps", {})
                    .get("layoutData", {})
                    .get("sitecore", {})
                    .get("context", {})
                    .get("cinema", {})
                    .get("cinemaId", {})
                    .get("value")
                )
            else:
                logging.warning("Не знайдено __NEXT_DATA__ на сторінці %s", repertuar_url)
        except requests.RequestException as exc:
            logging.warning("Не вдалося прочитати сторінку %s: %s", repertuar_url, exc)

        if not self.cinema_id:
            known_id = KNOWN_CINEMA_IDS.get(self.cinema_slug)
            if known_id:
                self.cinema_id = known_id
                logging.info(
                    "cinemaId для '%s' взято з вбудованого мапінгу: %s",
                    self.cinema_slug,
                    self.cinema_id,
                )

        # Fallback for servers/IPs where HTML page is blocked (403), but microservice API is available.
        if not self.cinema_id:
            self.cinema_id = self._resolve_cinema_id_from_api()

        if not self.cinema_id:
            logging.warning("Не вдалося отримати cinemaId для Multikino. Команди розкладу тимчасово недоступні.")

        if not self.build_id:
            logging.warning(
                "buildId недоступний; метадані фільмів будуть братися з showings API/рейтингів."
            )

    def ensure_auth(self) -> None:
        if self._auth_ready:
            return

        try:
            response = self.session.post(
                f"{self.base_url}/api/microservice/auth/token",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code == 403:
                logging.warning("auth/token повернув 403. Продовжую без auth-токена.")
                self._auth_ready = False
                return
            response.raise_for_status()
            self._auth_ready = True
        except requests.RequestException as exc:
            logging.warning("Не вдалося отримати auth token: %s. Продовжую без нього.", exc)
            self._auth_ready = False

    def _resolve_cinema_id_from_api(self) -> str | None:
        try:
            response = self.session.get(
                f"{self.base_url}/api/microservice/showings/cinemas",
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logging.warning("Не вдалося отримати список кінотеатрів через API: %s", exc)
            return None

        for bucket in payload.get("result") or []:
            for cinema in bucket.get("cinemas") or []:
                whats_on_url = str(cinema.get("whatsOnUrl") or "")
                slug = self._extract_cinema_slug_from_whats_on_url(whats_on_url)
                if slug == self.cinema_slug:
                    cinema_id = str(cinema.get("cinemaId") or "").strip()
                    if cinema_id:
                        logging.info(
                            "cinemaId для '%s' знайдено через API: %s",
                            self.cinema_slug,
                            cinema_id,
                        )
                        return cinema_id
        return None

    def get_showings_for_day(self, day: date) -> list[dict[str, Any]]:
        self.ensure_auth()
        if not self.cinema_id:
            raise RuntimeError("Клієнт не ініціалізований")

        response = self.session.get(
            f"{self.base_url}/api/microservice/showings/cinemas/{self.cinema_id}/films",
            params={
                "showingDate": day.isoformat(),
                "minEmbargoLevel": 2,
                "includesSession": "true",
                "includeSessionAttributes": "true",
            },
            timeout=30,
        )
        if response.status_code == 401:
            logging.info("showings повернув 401. Повторюю запит після оновлення auth token.")
            self._auth_ready = False
            self.ensure_auth()
            response = self.session.get(
                f"{self.base_url}/api/microservice/showings/cinemas/{self.cinema_id}/films",
                params={
                    "showingDate": day.isoformat(),
                    "minEmbargoLevel": 2,
                    "includesSession": "true",
                    "includeSessionAttributes": "true",
                },
                timeout=30,
            )
        response.raise_for_status()
        payload = response.json()
        return payload.get("result") or []

    def get_film_metadata(self, film_id: str, film_url: str, fallback_title: str) -> FilmMetadata:
        cached = self._film_meta_cache.get(film_id)
        if cached:
            return cached

        slug = self._extract_slug(film_url)
        metadata = FilmMetadata(film_id=film_id, title=fallback_title, release_year=None)

        if not self.build_id or not slug:
            self._film_meta_cache[film_id] = metadata
            return metadata

        details_url = f"{self.base_url}/_next/data/{self.build_id}/filmy/{slug}.json"
        response = self.session.get(details_url, timeout=30)
        if response.status_code != 200:
            self._film_meta_cache[film_id] = metadata
            return metadata

        payload = response.json()
        fields = self._find_film_fields(payload, film_id) or (
            payload.get("pageProps", {})
            .get("layoutData", {})
            .get("sitecore", {})
            .get("context", {})
            .get("route", {})
            .get("fields", {})
        )

        metadata.title = fields.get("filmName", {}).get("value") or fallback_title
        metadata.original_title = fields.get("originalTitle", {}).get("value") or ""
        metadata.synopsis_short = fields.get("shortSynopsis", {}).get("value") or ""

        release_ts = fields.get("releaseDate", {}).get("dateValue")
        if isinstance(release_ts, (int, float)) and release_ts > 0:
            metadata.release_year = datetime.fromtimestamp(release_ts / 1000).year

        metadata.genres = extract_genres(fields.get("genres", {}).get("targetItems"))

        metadata.attributes = {
            normalize_text(
                item.get("attributeName", {}).get("value")
                or item.get("name", {}).get("value")
                or item.get("shortName", {}).get("value")
                or ""
            )
            for item in fields.get("attributes", {}).get("targetItems", [])
        }
        metadata.attributes = {value for value in metadata.attributes if value}

        if metadata.release_year is None:
            # Fallback to release year from slug page route data if present in alternative shape.
            route_release_value = (
                payload.get("pageProps", {})
                .get("layoutData", {})
                .get("sitecore", {})
                .get("context", {})
                .get("cinema", {})
                .get("releaseDate", {})
                .get("value")
            )
            if isinstance(route_release_value, str) and len(route_release_value) >= 4:
                try:
                    metadata.release_year = int(route_release_value[:4])
                except ValueError:
                    pass

        inferred_year = infer_release_year_from_synopsis(
            title=metadata.title,
            synopsis=metadata.synopsis_short,
            current_release_year=metadata.release_year,
        )
        if inferred_year is not None:
            metadata.release_year = inferred_year

        self._film_meta_cache[film_id] = metadata
        return metadata

    @staticmethod
    def _extract_slug(film_url: str) -> str | None:
        try:
            path = urlparse(film_url).path
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2 and parts[0] == "filmy":
                return parts[1]
        except Exception:
            return None
        return None

    @staticmethod
    def _extract_cinema_slug_from_whats_on_url(whats_on_url: str) -> str | None:
        try:
            path = urlparse(whats_on_url).path
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 3 and parts[0] == "repertuar":
                return parts[1]
        except Exception:
            return None
        return None

    @staticmethod
    def _find_film_fields(payload: dict[str, Any], film_id: str) -> dict[str, Any] | None:
        stack: list[Any] = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                node_film_id = node.get("filmId")
                if (
                    isinstance(node_film_id, dict)
                    and node_film_id.get("value") == film_id
                    and "filmName" in node
                ):
                    return node
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return None


class RatingsProvider:
    def __init__(
        self,
        tmdb_api_key: str = "",
        omdb_api_key: str = "",
        session: requests.Session | None = None,
    ) -> None:
        self.tmdb_api_key = tmdb_api_key.strip()
        self.omdb_api_key = omdb_api_key.strip()
        self.session = session or requests.Session()
        self._cache: dict[tuple[str, int | None], FilmRatings] = {}
        self._tmdb_imdb_cache: dict[int, str] = {}

    def enabled(self) -> bool:
        return bool(self.tmdb_api_key or self.omdb_api_key)

    def get_ratings(
        self,
        title: str,
        year: int | None,
        original_title: str = "",
    ) -> FilmRatings:
        cache_key = (normalize_text(title), year)
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        ratings = FilmRatings()
        tmdb_movie_id: int | None = None
        imdb_id = ""

        if self.tmdb_api_key:
            tmdb_result = self._search_tmdb_best_match(title=title, year=year, original_title=original_title)
            if tmdb_result:
                tmdb_movie_id = tmdb_result.get("id")
                vote_average = tmdb_result.get("vote_average")
                vote_count = tmdb_result.get("vote_count")
                if isinstance(vote_average, (int, float)):
                    ratings.tmdb_vote_average = float(vote_average)
                if isinstance(vote_count, int):
                    ratings.tmdb_vote_count = vote_count

        if tmdb_movie_id is not None and self.tmdb_api_key:
            imdb_id = self._get_tmdb_imdb_id(tmdb_movie_id)

        if self.omdb_api_key:
            omdb_payload = self._get_omdb_payload(title=title, year=year, imdb_id=imdb_id)
            if omdb_payload:
                imdb_rating = omdb_payload.get("imdbRating")
                metascore = omdb_payload.get("Metascore")
                omdb_genre_raw = omdb_payload.get("Genre")
                omdb_year = self._parse_omdb_year(omdb_payload.get("Year"))
                if isinstance(imdb_rating, str) and imdb_rating != "N/A":
                    ratings.omdb_imdb_rating = imdb_rating
                if isinstance(metascore, str) and metascore != "N/A":
                    ratings.omdb_metascore = metascore
                ratings.omdb_year = omdb_year
                if isinstance(omdb_genre_raw, str) and omdb_genre_raw != "N/A":
                    parsed_genres = tuple(
                        g.strip()
                        for g in omdb_genre_raw.split(",")
                        if g.strip()
                    )
                    ratings.omdb_genres = parsed_genres
                for item in omdb_payload.get("Ratings") or []:
                    source = item.get("Source")
                    value = item.get("Value")
                    if source == "Rotten Tomatoes" and isinstance(value, str):
                        ratings.omdb_rotten_tomatoes = value

        self._cache[cache_key] = ratings
        return ratings

    def _search_tmdb_best_match(
        self,
        title: str,
        year: int | None,
        original_title: str = "",
    ) -> dict[str, Any] | None:
        title_candidates = [title.strip()]
        if original_title.strip() and normalize_text(original_title) != normalize_text(title):
            title_candidates.append(original_title.strip())

        best_movie: dict[str, Any] | None = None
        best_score = -10**9
        for candidate in title_candidates:
            if not candidate:
                continue
            query_variants: list[dict[str, Any]] = []
            params_with_year: dict[str, Any] = {"api_key": self.tmdb_api_key, "query": candidate}
            if year:
                params_with_year["year"] = year
            query_variants.append(params_with_year)
            if year:
                # Fallback when local year is a re-release year and TMDb result lives under original year.
                query_variants.append({"api_key": self.tmdb_api_key, "query": candidate})

            for params in query_variants:
                try:
                    response = self.session.get(
                        "https://api.themoviedb.org/3/search/movie",
                        params=params,
                        timeout=20,
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    logging.warning("TMDb search failed for '%s': %s", candidate, exc)
                    continue

                for index, movie in enumerate(payload.get("results") or []):
                    score = self._score_tmdb_result(
                        wanted_title=title,
                        wanted_year=year,
                        movie=movie,
                        position=index,
                    )
                    if score > best_score:
                        best_score = score
                        best_movie = movie

        return best_movie

    @staticmethod
    def _score_tmdb_result(
        wanted_title: str,
        wanted_year: int | None,
        movie: dict[str, Any],
        position: int,
    ) -> int:
        score = 0
        wanted_norm = normalize_text(wanted_title)
        candidate_title = str(movie.get("title") or "")
        candidate_original = str(movie.get("original_title") or "")
        candidate_norm = normalize_text(candidate_title)
        candidate_orig_norm = normalize_text(candidate_original)

        if candidate_norm == wanted_norm or candidate_orig_norm == wanted_norm:
            score += 8
        elif wanted_norm in candidate_norm or wanted_norm in candidate_orig_norm:
            score += 4

        release_date = movie.get("release_date") or ""
        candidate_year: int | None = None
        if isinstance(release_date, str) and len(release_date) >= 4:
            try:
                candidate_year = int(release_date[:4])
            except ValueError:
                candidate_year = None

        if wanted_year and candidate_year:
            if wanted_year == candidate_year:
                score += 8
            elif abs(wanted_year - candidate_year) <= 1:
                score += 3
            else:
                score -= 3

        score += max(0, 5 - position)
        return score

    def _get_tmdb_imdb_id(self, movie_id: int) -> str:
        cached = self._tmdb_imdb_cache.get(movie_id)
        if cached is not None:
            return cached

        imdb_id = ""
        try:
            response = self.session.get(
                f"https://api.themoviedb.org/3/movie/{movie_id}",
                params={"api_key": self.tmdb_api_key},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            raw = payload.get("imdb_id")
            if isinstance(raw, str):
                imdb_id = raw
        except Exception as exc:
            logging.warning("TMDb details failed for movie_id=%s: %s", movie_id, exc)

        self._tmdb_imdb_cache[movie_id] = imdb_id
        return imdb_id

    def _get_omdb_payload(self, title: str, year: int | None, imdb_id: str = "") -> dict[str, Any] | None:
        queries: list[dict[str, Any]] = []
        if imdb_id:
            queries.append({"i": imdb_id})

        title_query = {"t": title}
        if year:
            title_query["y"] = str(year)
        queries.append(title_query)
        if year:
            queries.append({"t": title})

        for query in queries:
            params = {"apikey": self.omdb_api_key, **query}
            try:
                response = self.session.get("https://www.omdbapi.com/", params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logging.warning("OMDb request failed for query=%s: %s", query, exc)
                continue

            if str(payload.get("Response")) == "True":
                return payload

        return None

    @staticmethod
    def _parse_omdb_year(raw_year: Any) -> int | None:
        if not isinstance(raw_year, str):
            return None
        match = YEAR_IN_TEXT_RE.search(raw_year)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None


def is_kids_movie(metadata: FilmMetadata) -> bool:
    genres = {normalize_text(g) for g in metadata.genres}
    attributes = {normalize_text(a) for a in metadata.attributes}
    title = normalize_text(metadata.title)

    if any(keyword in genre for genre in genres for keyword in KIDS_GENRE_KEYWORDS):
        return True
    if any(keyword in attr for attr in attributes for keyword in KIDS_ATTRIBUTE_KEYWORDS):
        return True
    return any(keyword in title for keyword in KIDS_TITLE_KEYWORDS)


def parse_release_year(raw_release_date: Any) -> int | None:
    if not isinstance(raw_release_date, str) or len(raw_release_date) < 4:
        return None
    try:
        return int(raw_release_date[:4])
    except ValueError:
        return None


def extract_genres(values: list[dict[str, Any]] | None) -> set[str]:
    genres: set[str] = set()
    for item in values or []:
        name = (
            item.get("genreName", {}).get("value")
            or item.get("genreName")
            or item.get("name")
            or ""
        )
        text = str(name).strip()
        if text:
            genres.add(text)
    return genres


def infer_release_year_from_synopsis(
    title: str,
    synopsis: str,
    current_release_year: int | None,
) -> int | None:
    if not synopsis:
        return None

    text_norm = normalize_text(synopsis)
    title_norm = normalize_text(title)

    if any(hint in text_norm for hint in SEQUEL_TEXT_HINTS):
        return None

    # Avoid forcing old year for explicit sequels in title.
    if re.search(r"\b(?:ii|iii|iv|v|vi|vii|viii|ix|x|2|3|4|5)\b", title_norm):
        return None

    years = [int(y) for y in YEAR_IN_TEXT_RE.findall(synopsis)]
    years = [y for y in years if 1900 <= y <= datetime.now().year + 1]
    if not years:
        return None

    oldest = min(years)
    if current_release_year is None:
        return oldest

    # Re-release case: API gives modern date, synopsis clearly references original year.
    if current_release_year - oldest >= 10:
        return oldest
    return None


def extract_times_for_day(showing_groups: list[dict[str, Any]], day: date) -> list[str]:
    times: set[str] = set()
    for group in showing_groups or []:
        for session in group.get("sessions") or []:
            start_raw = session.get("showTimeWithTimeZone") or session.get("startTime")
            if not isinstance(start_raw, str):
                continue
            dt = datetime.fromisoformat(start_raw)
            if dt.date() != day:
                continue
            times.add(dt.strftime("%H:%M"))
    return sorted(times)


def collect_week_schedule(
    client: MultikinoClient,
    start_day: date,
    days: int,
    ratings_provider: RatingsProvider | None = None,
) -> list[FilmSchedule]:
    films: dict[str, FilmSchedule] = {}

    for offset in range(days):
        day = start_day + timedelta(days=offset)
        day_showings = client.get_showings_for_day(day)
        for film in day_showings:
            film_id = film.get("filmId")
            if not film_id:
                continue

            raw_title = film.get("filmTitle") or "Без назви"
            film_url = film.get("filmUrl") or ""
            release_year = parse_release_year(film.get("releaseDate"))

            metadata = client.get_film_metadata(film_id, film_url, raw_title)
            if metadata.release_year is None:
                metadata.release_year = release_year
            if not metadata.title:
                metadata.title = raw_title
            if not metadata.genres:
                metadata.genres = extract_genres(film.get("genres"))

            if is_kids_movie(metadata):
                continue

            times = extract_times_for_day(film.get("showingGroups") or [], day)
            if not times:
                continue

            item = films.get(film_id)
            if not item:
                ratings = FilmRatings()
                if ratings_provider and ratings_provider.enabled():
                    ratings = ratings_provider.get_ratings(
                        title=metadata.title,
                        year=metadata.release_year,
                        original_title=metadata.original_title,
                    )
                genres = tuple(sorted(metadata.genres))
                local_genres_norm = {normalize_text(g) for g in metadata.genres}
                omdb_genres_norm = {normalize_text(g) for g in ratings.omdb_genres}
                # Якщо локальний жанр від кінотеатру підозрілий (наприклад "animowany"),
                # а OMDb дає інші жанри, беремо OMDb як більш точний.
                if ratings.omdb_genres:
                    if not genres:
                        genres = ratings.omdb_genres
                    elif (
                        "animowany" in local_genres_norm
                        and "animowany" not in omdb_genres_norm
                        and "animation" not in omdb_genres_norm
                    ):
                        genres = ratings.omdb_genres
                release_year_for_output = metadata.release_year
                if ratings.omdb_year is not None:
                    if release_year_for_output is None or release_year_for_output - ratings.omdb_year >= 10:
                        release_year_for_output = ratings.omdb_year
                item = FilmSchedule(
                    film_id=film_id,
                    title=metadata.title,
                    release_year=release_year_for_output,
                    genres=genres,
                    ratings=ratings,
                )
                films[film_id] = item
            item.add_sessions(day, times)

    return sorted(
        films.values(),
        key=lambda f: (min(f.sessions_by_date.keys()), f.title),
    )


def format_sessions_by_day(schedule: FilmSchedule, locale: str = "uk") -> str:
    weekday_names = weekday_labels(locale)
    chunks = []
    for day in sorted(schedule.sessions_by_date):
        times = schedule.sessions_by_date[day]
        if len(times) > 6:
            shown = ", ".join(times[:6])
            times_text = f"{shown} +{len(times) - 6}"
        else:
            times_text = ", ".join(times)
        chunks.append(f"{weekday_names[day.weekday()]} {day:%d.%m}: {times_text}")
    return " | ".join(chunks)


def format_ratings_lines(ratings: FilmRatings) -> list[str]:
    parts: list[str] = []
    if ratings.tmdb_vote_average is not None:
        tmdb_text = f"TMDb {ratings.tmdb_vote_average:.1f}/10"
        if ratings.tmdb_vote_count is not None:
            tmdb_text += f" ({ratings.tmdb_vote_count})"
        parts.append(tmdb_text)
    if ratings.omdb_imdb_rating:
        parts.append(f"OMDb IMDb {ratings.omdb_imdb_rating}/10")
    if ratings.omdb_rotten_tomatoes:
        parts.append(f"OMDb RT {ratings.omdb_rotten_tomatoes}")
    if ratings.omdb_metascore:
        parts.append(f"OMDb Metascore {ratings.omdb_metascore}/100")
    return parts


def _append_film_block(
    lines: list[str],
    film: FilmSchedule,
    texts: dict[str, str],
    include_sessions: bool,
    locale: str,
) -> None:
    title = html.escape(film.title)
    year_suffix = f" ({film.release_year})" if film.release_year is not None else ""
    genres_text = ", ".join(film.genres) if film.genres else texts["unknown_genre"]

    lines.append(f"{MOVIE_MARK} <b>{title}</b>{year_suffix}")
    lines.append(f"  {GENRE_MARK} {texts['genre_label']}: {html.escape(genres_text)}")
    for rating_text in format_ratings_lines(film.ratings):
        lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
    if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
        lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
    if include_sessions:
        lines.append(f"  {SESSIONS_MARK} {format_sessions_by_day(film, locale=locale)}")
    lines.append(FILM_SEPARATOR)


def _append_regular_section(
    lines: list[str],
    films: list[FilmSchedule],
    texts: dict[str, str],
    include_sessions: bool,
    locale: str,
) -> None:
    if not films:
        lines.append(texts["no_items"])
        return
    for film in films:
        _append_film_block(
            lines,
            film=film,
            texts=texts,
            include_sessions=include_sessions,
            locale=locale,
        )


def _append_retro_section(
    lines: list[str],
    films: list[FilmSchedule],
    texts: dict[str, str],
    include_sessions: bool,
    locale: str,
) -> None:
    if not films:
        lines.append(texts["no_items"])
        return

    by_decade: dict[int, list[FilmSchedule]] = {}
    for film in films:
        decade = (film.release_year // 10) * 10  # type: ignore[operator]
        by_decade.setdefault(decade, []).append(film)

    for decade in sorted(by_decade.keys(), reverse=True):
        lines.append(f"{decade}{texts['decade_suffix']}:")
        for film in sorted(by_decade[decade], key=lambda f: f.title):
            _append_film_block(
                lines,
                film=film,
                texts=texts,
                include_sessions=include_sessions,
                locale=locale,
            )


def _format_report(
    schedules: list[FilmSchedule],
    start_day: date,
    days: int,
    modern_year_threshold: int,
    ratings_enabled: bool,
    list_only: bool,
    locale: str,
    cinema_label: str,
) -> str:
    texts = locale_text(locale)
    end_day = start_day + timedelta(days=days - 1)
    header = (
        f"{texts['cinema_label']}: {cinema_label}\n"
        f"{texts['period_label']}: {start_day:%d.%m.%Y} - {end_day:%d.%m.%Y}\n"
        f"{texts['list_only_format'] if list_only else texts['kids_filtered']}\n"
    )
    ratings_status = texts["ratings_enabled"] if ratings_enabled else texts["ratings_disabled"]

    if not schedules:
        empty_text = texts["no_movies"] if list_only else texts["no_sessions"]
        return header + f"{RATINGS_MARK} {ratings_status}\n\n{empty_text}"

    modern = [s for s in schedules if s.release_year is not None and s.release_year >= modern_year_threshold]
    retro = [s for s in schedules if s.release_year is not None and s.release_year < modern_year_threshold]
    unknown = [s for s in schedules if s.release_year is None]

    lines = [header]
    lines.append(f"{RATINGS_MARK} {ratings_status}")
    lines.append("")
    lines.append(texts["modern_section"].format(year=modern_year_threshold))
    _append_regular_section(
        lines,
        modern,
        texts,
        include_sessions=not list_only,
        locale=locale,
    )

    lines.append("")
    lines.append(texts["retro_section"])
    _append_retro_section(
        lines,
        retro,
        texts,
        include_sessions=not list_only,
        locale=locale,
    )

    if unknown:
        lines.append("")
        lines.append(texts["unknown_year_section"])
        _append_regular_section(
            lines,
            unknown,
            texts,
            include_sessions=not list_only,
            locale=locale,
        )

    return "\n".join(lines).strip()


def format_week_report(
    schedules: list[FilmSchedule],
    start_day: date,
    days: int,
    modern_year_threshold: int,
    ratings_enabled: bool = False,
    locale: str = "uk",
    cinema_label: str = "Warszawa Młociny",
) -> str:
    return _format_report(
        schedules=schedules,
        start_day=start_day,
        days=days,
        modern_year_threshold=modern_year_threshold,
        ratings_enabled=ratings_enabled,
        list_only=False,
        locale=locale,
        cinema_label=cinema_label,
    )


def split_for_telegram(message: str, limit: int = 3900) -> list[str]:
    if len(message) <= limit:
        return [message]

    parts: list[str] = []
    current = []
    size = 0
    for line in message.splitlines():
        line_size = len(line) + 1
        if current and size + line_size > limit:
            parts.append("\n".join(current))
            current = [line]
            size = line_size
        else:
            current.append(line)
            size += line_size
    if current:
        parts.append("\n".join(current))
    return parts


def is_multikino_forbidden_error(exc: Exception) -> bool:
    if not isinstance(exc, requests.HTTPError):
        return False
    response = exc.response
    if response is None or response.status_code != 403:
        return False
    return "multikino.pl" in str(response.url or "")


def extract_command(text: str) -> str:
    token = (text or "").strip().split(maxsplit=1)[0] if (text or "").strip() else ""
    if not token.startswith("/"):
        return ""
    return token.split("@", 1)[0]


def format_list_only_report(
    schedules: list[FilmSchedule],
    start_day: date,
    days: int,
    modern_year_threshold: int,
    ratings_enabled: bool = False,
    locale: str = "uk",
    cinema_label: str = "Warszawa Młociny",
) -> str:
    return _format_report(
        schedules=schedules,
        start_day=start_day,
        days=days,
        modern_year_threshold=modern_year_threshold,
        ratings_enabled=ratings_enabled,
        list_only=True,
        locale=locale,
        cinema_label=cinema_label,
    )


@dataclass(frozen=True)
class WebhookConfig:
    url: str
    path: str
    secret_token: str
    listen_host: str
    listen_port: int
    cert_file: str | None = None
    key_file: str | None = None
    upload_certificate: bool = False
    drop_pending_updates: bool = False
    max_connections: int = 40
    ip_address: str | None = None

    @property
    def direct_tls_enabled(self) -> bool:
        return bool(self.cert_file and self.key_file)


def resolve_webhook_secret(token: str) -> str:
    raw_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if raw_secret:
        secret = raw_secret
    else:
        secret = hashlib.sha256(token.encode("utf-8")).hexdigest()

    if not WEBHOOK_SECRET_RE.fullmatch(secret):
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET має містити тільки A-Z, a-z, 0-9, '_' або '-' і бути до 256 символів."
        )
    return secret


def build_webhook_config(token: str, raw_url: str) -> WebhookConfig:
    webhook_url = raw_url.strip()
    if not webhook_url:
        raise RuntimeError("Для webhook-режиму треба задати TELEGRAM_WEBHOOK_URL у .env.")

    parsed = urlparse(webhook_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("TELEGRAM_WEBHOOK_URL має бути повним HTTPS URL, наприклад https://host:8443.")

    secret_token = resolve_webhook_secret(token)
    webhook_path = parsed.path or "/"
    if webhook_path == "/":
        webhook_path = f"/telegram/webhook/{secret_token[:32]}"
        webhook_url = webhook_url.rstrip("/") + webhook_path

    listen_host = os.getenv("TELEGRAM_WEBHOOK_LISTEN_HOST", "0.0.0.0").strip() or "0.0.0.0"
    listen_port = read_env_int("TELEGRAM_WEBHOOK_LISTEN_PORT", 8080)
    cert_file = os.getenv("TELEGRAM_WEBHOOK_CERT_FILE", "").strip() or None
    key_file = os.getenv("TELEGRAM_WEBHOOK_KEY_FILE", "").strip() or None
    upload_certificate = read_env_bool("TELEGRAM_WEBHOOK_UPLOAD_CERT", False)
    drop_pending_updates = read_env_bool("TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES", False)
    max_connections = read_env_int("TELEGRAM_WEBHOOK_MAX_CONNECTIONS", 40)
    ip_address = os.getenv("TELEGRAM_WEBHOOK_IP_ADDRESS", "").strip() or None

    if bool(cert_file) != bool(key_file):
        raise RuntimeError("TELEGRAM_WEBHOOK_CERT_FILE і TELEGRAM_WEBHOOK_KEY_FILE треба задавати разом.")

    return WebhookConfig(
        url=webhook_url,
        path=webhook_path,
        secret_token=secret_token,
        listen_host=listen_host,
        listen_port=listen_port,
        cert_file=cert_file,
        key_file=key_file,
        upload_certificate=upload_certificate,
        drop_pending_updates=drop_pending_updates,
        max_connections=max(1, min(max_connections, 100)),
        ip_address=ip_address,
    )


def make_webhook_handler(bot: "TelegramBot", config: WebhookConfig) -> type[BaseHTTPRequestHandler]:
    class TelegramWebhookHandler(BaseHTTPRequestHandler):
        server_version = "KinoTelegramWebhook/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            logging.info("Webhook HTTP: " + format, *args)

        def _send_plain(self, status: HTTPStatus, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            request_path = urlparse(self.path).path
            if request_path == "/healthz":
                self._send_plain(HTTPStatus.OK, "ok")
                return
            self._send_plain(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            request_path = urlparse(self.path).path
            if request_path != config.path:
                self._send_plain(HTTPStatus.NOT_FOUND, "not found")
                return

            header_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header_secret != config.secret_token:
                self._send_plain(HTTPStatus.FORBIDDEN, "forbidden")
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_plain(HTTPStatus.BAD_REQUEST, "bad content length")
                return

            if content_length <= 0 or content_length > 1024 * 1024:
                self._send_plain(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "bad payload size")
                return

            try:
                update = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except json.JSONDecodeError:
                self._send_plain(HTTPStatus.BAD_REQUEST, "bad json")
                return

            bot.handle_update_async(update)
            self._send_plain(HTTPStatus.OK, "ok")

    return TelegramWebhookHandler


class TelegramBot:
    def __init__(
        self,
        token: str,
        kino_client: MultikinoClient,
        ratings_provider: RatingsProvider | None,
        timezone_name: str,
        modern_year_threshold: int,
        week_days: int,
        locale: str,
        locale_auto: bool,
        cinema_label: str,
    ) -> None:
        self.token = token
        self.kino_client = kino_client
        self.ratings_provider = ratings_provider
        self.tz = ZoneInfo(timezone_name)
        self.modern_year_threshold = modern_year_threshold
        self.week_days = week_days
        self.locale = resolve_locale(locale)
        self.locale_auto = locale_auto
        self.cinema_label = cinema_label
        self._commands_text_cache: dict[str, str] = {}
        self._help_text_cache: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="telegram-update")
        self._seen_update_ids: deque[int] = deque()
        self._seen_update_id_set: set[int] = set()
        self._seen_update_lock = threading.Lock()
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

    def run(self) -> None:
        self.run_polling()

    def run_polling(self) -> None:
        logging.info("Telegram-бот запущено в polling-режимі.")
        self._delete_webhook()
        self._register_commands()
        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self.offset = update["update_id"] + 1
                    self._handle_update(update)
            except requests.RequestException as exc:
                logging.exception("Помилка мережі: %s", exc)
                time.sleep(3)
            except Exception as exc:
                logging.exception("Неочікувана помилка: %s", exc)
                time.sleep(3)

    def run_webhook(self, config: WebhookConfig) -> None:
        logging.info("Telegram-бот запущено в webhook-режимі.")
        self._register_commands()
        handler = make_webhook_handler(self, config)
        server = ThreadingHTTPServer((config.listen_host, config.listen_port), handler)

        if config.direct_tls_enabled:
            assert config.cert_file is not None
            assert config.key_file is not None
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(certfile=config.cert_file, keyfile=config.key_file)
            server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
            logging.info(
                "Webhook HTTP-сервер слухає HTTPS на %s:%s",
                config.listen_host,
                config.listen_port,
            )
        else:
            logging.info(
                "Webhook HTTP-сервер слухає HTTP на %s:%s",
                config.listen_host,
                config.listen_port,
            )

        self._set_webhook(config)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            logging.info("Зупинка webhook-сервера.")
        finally:
            server.server_close()
            self.shutdown()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _get_updates(self) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.api_base}/getUpdates",
            params={"offset": self.offset, "timeout": 30},
            timeout=35,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload}")
        return payload.get("result", [])

    def _delete_webhook(self) -> None:
        try:
            response = requests.post(
                f"{self.api_base}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logging.warning("Не вдалося вимкнути webhook перед polling: %s", payload)
        except Exception as exc:
            logging.warning("Не вдалося викликати deleteWebhook: %s", exc)

    def _set_webhook(self, config: WebhookConfig) -> None:
        payload: dict[str, Any] = {
            "url": config.url,
            "allowed_updates": WEBHOOK_ALLOWED_UPDATES,
            "secret_token": config.secret_token,
            "drop_pending_updates": config.drop_pending_updates,
            "max_connections": config.max_connections,
        }
        if config.ip_address:
            payload["ip_address"] = config.ip_address

        if config.upload_certificate:
            if not config.cert_file:
                raise RuntimeError("TELEGRAM_WEBHOOK_UPLOAD_CERT=1 потребує TELEGRAM_WEBHOOK_CERT_FILE.")
            form_payload = {
                "url": config.url,
                "allowed_updates": json.dumps(WEBHOOK_ALLOWED_UPDATES),
                "secret_token": config.secret_token,
                "drop_pending_updates": "true" if config.drop_pending_updates else "false",
                "max_connections": str(config.max_connections),
            }
            if config.ip_address:
                form_payload["ip_address"] = config.ip_address
            with open(config.cert_file, "rb") as cert_handle:
                response = requests.post(
                    f"{self.api_base}/setWebhook",
                    data=form_payload,
                    files={"certificate": cert_handle},
                    timeout=60,
                )
        else:
            response = requests.post(
                f"{self.api_base}/setWebhook",
                json=payload,
                timeout=30,
            )

        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram setWebhook failed: {result}")
        logging.info("Webhook зареєстровано: %s", config.url)

    def handle_update_async(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            with self._seen_update_lock:
                if update_id in self._seen_update_id_set:
                    logging.info("Повторний Telegram update_id=%s пропущено.", update_id)
                    return
                if len(self._seen_update_ids) >= 500:
                    old_update_id = self._seen_update_ids.popleft()
                    self._seen_update_id_set.discard(old_update_id)
                self._seen_update_ids.append(update_id)
                self._seen_update_id_set.add(update_id)

        future = self._executor.submit(self._handle_update, update)
        future.add_done_callback(self._log_async_update_error)

    def _log_async_update_error(self, future: Future[None]) -> None:
        try:
            future.result()
        except Exception as exc:
            logging.exception("Не вдалося обробити Telegram update: %s", exc)

    def _send_message(self, chat_id: int, text: str) -> None:
        for part in split_for_telegram(text):
            response = requests.post(
                f"{self.api_base}/sendMessage",
                json={"chat_id": chat_id, "text": part, "parse_mode": "HTML"},
                timeout=30,
            )
            response.raise_for_status()

    def _commands_text(self, locale_code: str) -> str:
        cached = self._commands_text_cache.get(locale_code)
        if cached:
            return cached
        value = build_commands_text(locale_code)
        self._commands_text_cache[locale_code] = value
        return value

    def _help_text(self, locale_code: str) -> str:
        cached = self._help_text_cache.get(locale_code)
        if cached:
            return cached
        value = build_help_text(locale_code, locale_code)
        self._help_text_cache[locale_code] = value
        return value

    def _register_commands(self) -> None:
        try:
            response = requests.post(f"{self.api_base}/setMyCommands", json={"commands": build_bot_commands(self.locale)}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logging.warning("Не вдалося оновити список команд бота: %s", payload)

            for locale_code in SUPPORTED_LOCALES:
                response = requests.post(
                    f"{self.api_base}/setMyCommands",
                    json={
                        "commands": build_bot_commands(locale_code),
                        "language_code": locale_code,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    logging.warning(
                        "Не вдалося оновити список команд бота для locale=%s: %s",
                        locale_code,
                        payload,
                    )
        except Exception as exc:
            logging.warning("Не вдалося зареєструвати команди в Telegram: %s", exc)

    def _effective_locale(self, message: dict[str, Any]) -> str:
        if not self.locale_auto:
            return self.locale
        user = message.get("from") or {}
        raw_locale = str(user.get("language_code") or "").strip()
        detected = detect_supported_locale(raw_locale)
        return detected or self.locale

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        command = extract_command(text)
        current_locale = self._effective_locale(message)
        texts = locale_text(current_locale)

        if command == "/start":
            intro = texts["start_intro"].format(cinema_label=self.cinema_label)
            self._send_message(chat_id, f"{intro}\n\n{self._commands_text(current_locale)}")
            return

        if command == "/help":
            self._send_message(chat_id, self._help_text(current_locale))
            return

        if command == "/commands":
            self._send_message(chat_id, self._commands_text(current_locale))
            return

        if command in REPORT_COMMANDS:
            days, list_only, start_offset_days = REPORT_COMMANDS[command]
            if command.startswith("/week"):
                days = self.week_days
            self._send_report(
                chat_id,
                days=days,
                list_only=list_only,
                start_offset_days=start_offset_days,
                locale=current_locale,
            )
            return

        self._send_message(
            chat_id,
            f"{texts['unknown_command']}\n\n{self._commands_text(current_locale)}",
        )

    def _send_report(
        self,
        chat_id: int,
        days: int,
        list_only: bool = False,
        start_offset_days: int = 0,
        locale: str = "uk",
    ) -> None:
        texts = locale_text(locale)
        start_day = datetime.now(self.tz).date() + timedelta(days=start_offset_days)
        try:
            schedules = collect_week_schedule(
                self.kino_client,
                start_day,
                days=days,
                ratings_provider=self.ratings_provider,
            )
            if list_only:
                report = format_list_only_report(
                    schedules=schedules,
                    start_day=start_day,
                    days=days,
                    modern_year_threshold=self.modern_year_threshold,
                    ratings_enabled=bool(self.ratings_provider and self.ratings_provider.enabled()),
                    locale=locale,
                    cinema_label=self.cinema_label,
                )
            else:
                report = format_week_report(
                    schedules=schedules,
                    start_day=start_day,
                    days=days,
                    modern_year_threshold=self.modern_year_threshold,
                    ratings_enabled=bool(self.ratings_provider and self.ratings_provider.enabled()),
                    locale=locale,
                    cinema_label=self.cinema_label,
                )
            self._send_message(chat_id, report)
        except Exception as exc:
            logging.exception("Не вдалося зібрати звіт: %s", exc)
            if is_multikino_forbidden_error(exc):
                self._send_message(chat_id, texts["multikino_ip_blocked"])
            else:
                self._send_message(chat_id, texts["schedule_fetch_failed"])


def build_client(cinema_slug: str) -> MultikinoClient:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8,uk;q=0.7",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{BASE_URL}/repertuar/{cinema_slug}/teraz-gramy",
            "Origin": BASE_URL,
        }
    )
    multikino_proxy = os.getenv("MULTIKINO_PROXY_URL", "").strip()
    if multikino_proxy:
        if multikino_proxy.startswith("https://"):
            logging.warning(
                "MULTIKINO_PROXY_URL починається з https://. Для CONNECT-проксі зазвичай потрібен http://."
            )
        session.proxies.update({"http": multikino_proxy, "https": multikino_proxy})
        logging.info("Для Multikino використовується проксі: %s", multikino_proxy)

    proxy_ca_bundle = os.getenv("MULTIKINO_PROXY_CA_BUNDLE", "").strip()
    if proxy_ca_bundle:
        session.verify = proxy_ca_bundle
        logging.info("Для проксі використовується CA bundle: %s", proxy_ca_bundle)

    proxy_insecure = normalize_text(os.getenv("MULTIKINO_PROXY_INSECURE", ""))
    if proxy_insecure in {"1", "true", "yes"}:
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logging.warning("УВАГА: MULTIKINO_PROXY_INSECURE увімкнено, TLS-перевірка вимкнена.")

    cinema_id_override = os.getenv("MULTIKINO_CINEMA_ID", "").strip() or None
    client = MultikinoClient(
        session=session,
        cinema_slug=cinema_slug,
        cinema_id_override=cinema_id_override,
    )
    client.initialize()
    return client


def run_print_week(
    client: MultikinoClient,
    ratings_provider: RatingsProvider | None,
    days: int,
    timezone_name: str,
    modern_year_threshold: int,
    locale: str,
    cinema_label: str,
) -> None:
    start_day = datetime.now(ZoneInfo(timezone_name)).date()
    schedules = collect_week_schedule(client, start_day, days=days, ratings_provider=ratings_provider)
    report = format_week_report(
        schedules=schedules,
        start_day=start_day,
        days=days,
        modern_year_threshold=modern_year_threshold,
        ratings_enabled=bool(ratings_provider and ratings_provider.enabled()),
        locale=locale,
        cinema_label=cinema_label,
    )
    print(report)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    dotenv_path = Path(__file__).resolve().parent / ".env"
    load_dotenv_file(dotenv_path)

    parser = argparse.ArgumentParser(description="Telegram-бот для репертуару Multikino")
    parser.add_argument("--print-week", action="store_true", help="Надрукувати звіт у консоль і завершити")
    parser.add_argument(
        "--cinema-slug",
        default=os.getenv("MULTIKINO_CINEMA_SLUG", DEFAULT_CINEMA_SLUG),
        help="slug кінотеатру з URL Multikino",
    )
    parser.add_argument(
        "--update-mode",
        choices=("auto", "polling", "webhook"),
        default=normalize_text(os.getenv("TELEGRAM_UPDATE_MODE", "auto")),
        help="як отримувати Telegram updates: polling або webhook",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.getenv("TELEGRAM_WEBHOOK_URL", ""),
        help="публічний HTTPS URL для Telegram webhook",
    )
    args = parser.parse_args()

    timezone_name = os.getenv("BOT_TIMEZONE", "Europe/Warsaw")
    locale = resolve_locale(os.getenv("BOT_LOCALE", "uk"))
    locale_auto = read_env_bool("BOT_LOCALE_AUTO", True)
    modern_year_threshold = read_env_int("MODERN_YEAR_THRESHOLD", 2010)
    week_days = read_env_int("WEEK_DAYS", 7)
    tmdb_api_key = os.getenv("TMDB_API_KEY", "").strip()
    omdb_api_key = os.getenv("OMDB_API_KEY", "").strip()
    cinema_label = resolve_cinema_label(args.cinema_slug)

    client = build_client(args.cinema_slug)
    ratings_provider: RatingsProvider | None = None
    if tmdb_api_key or omdb_api_key:
        ratings_provider = RatingsProvider(
            tmdb_api_key=tmdb_api_key,
            omdb_api_key=omdb_api_key,
        )
        logging.info(
            "Рейтинги увімкнено: TMDb=%s, OMDb=%s",
            "yes" if tmdb_api_key else "no",
            "yes" if omdb_api_key else "no",
        )
    else:
        logging.info("Рейтинги вимкнено: TMDB_API_KEY/OMDB_API_KEY не задані.")

    if args.print_week:
        run_print_week(
            client,
            ratings_provider=ratings_provider,
            days=week_days,
            timezone_name=timezone_name,
            modern_year_threshold=modern_year_threshold,
            locale=locale,
            cinema_label=cinema_label,
        )
        return

    token = resolve_telegram_token(dotenv_path)

    bot = TelegramBot(
        token=token,
        kino_client=client,
        ratings_provider=ratings_provider,
        timezone_name=timezone_name,
        modern_year_threshold=modern_year_threshold,
        week_days=week_days,
        locale=locale,
        locale_auto=locale_auto,
        cinema_label=cinema_label,
    )
    update_mode = args.update_mode
    if update_mode == "auto":
        update_mode = "webhook" if args.webhook_url.strip() else "polling"

    if update_mode == "webhook":
        webhook_config = build_webhook_config(token, args.webhook_url)
        bot.run_webhook(webhook_config)
    else:
        bot.run_polling()


if __name__ == "__main__":
    main()
