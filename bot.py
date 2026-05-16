#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://www.multikino.pl"
DEFAULT_CINEMA_SLUG = "warszawa-mlociny"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

WEEKDAY_UA = {
    0: "Пн",
    1: "Вт",
    2: "Ср",
    3: "Чт",
    4: "Пт",
    5: "Сб",
    6: "Нд",
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
BOT_COMMANDS = [
    {"command": "week", "description": "7 днів, із сеансами"},
    {"command": "week_l", "description": "7 днів, без сеансів"},
    {"command": "today", "description": "Сьогодні, із сеансами"},
    {"command": "today_l", "description": "Сьогодні, без сеансів"},
    {"command": "tomorrow", "description": "Завтра, із сеансами"},
    {"command": "tomorrow_l", "description": "Завтра, без сеансів"},
    {"command": "commands", "description": "Список доступних команд"},
    {"command": "help", "description": "Підказка"},
]


def normalize_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def read_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
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
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.cinema_slug = cinema_slug
        self.cinema_id: str | None = None
        self.build_id: str | None = None
        self._auth_ready = False
        self._film_meta_cache: dict[str, FilmMetadata] = {}

    def initialize(self) -> None:
        repertuar_url = f"{self.base_url}/repertuar/{self.cinema_slug}/teraz-gramy"
        response = self.session.get(repertuar_url, timeout=30)
        response.raise_for_status()

        match = NEXT_DATA_RE.search(response.text)
        if not match:
            raise RuntimeError("Не вдалося знайти __NEXT_DATA__ на сторінці Multikino")

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

        if not self.build_id:
            raise RuntimeError("Не вдалося отримати buildId із сторінки Multikino")
        if not self.cinema_id:
            raise RuntimeError("Не вдалося отримати cinemaId із сторінки Multikino")

    def ensure_auth(self) -> None:
        if self._auth_ready:
            return

        response = self.session.post(
            f"{self.base_url}/api/microservice/auth/token",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        self._auth_ready = True

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
        response.raise_for_status()
        payload = response.json()
        return payload.get("result") or []

    def get_film_metadata(self, film_id: str, film_url: str, fallback_title: str) -> FilmMetadata:
        cached = self._film_meta_cache.get(film_id)
        if cached:
            return cached

        if not self.build_id:
            raise RuntimeError("Немає buildId для запиту деталей фільму")

        slug = self._extract_slug(film_url)
        metadata = FilmMetadata(film_id=film_id, title=fallback_title, release_year=None)

        if not slug:
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
                if isinstance(imdb_rating, str) and imdb_rating != "N/A":
                    ratings.omdb_imdb_rating = imdb_rating
                if isinstance(metascore, str) and metascore != "N/A":
                    ratings.omdb_metascore = metascore
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
            params: dict[str, Any] = {"api_key": self.tmdb_api_key, "query": candidate}
            if year:
                params["year"] = year
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
                item = FilmSchedule(
                    film_id=film_id,
                    title=metadata.title,
                    release_year=metadata.release_year,
                    genres=genres,
                    ratings=ratings,
                )
                films[film_id] = item
            item.add_sessions(day, times)

    return sorted(
        films.values(),
        key=lambda f: (min(f.sessions_by_date.keys()), f.title),
    )


def format_sessions_by_day(schedule: FilmSchedule) -> str:
    chunks = []
    for day in sorted(schedule.sessions_by_date):
        times = schedule.sessions_by_date[day]
        if len(times) > 6:
            shown = ", ".join(times[:6])
            times_text = f"{shown} +{len(times) - 6}"
        else:
            times_text = ", ".join(times)
        chunks.append(f"{WEEKDAY_UA[day.weekday()]} {day:%d.%m}: {times_text}")
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


def format_week_report(
    schedules: list[FilmSchedule],
    start_day: date,
    days: int,
    modern_year_threshold: int,
    ratings_enabled: bool = False,
) -> str:
    end_day = start_day + timedelta(days=days - 1)
    header = (
        f"Кіно: Warszawa Młociny\n"
        f"Період: {start_day:%d.%m.%Y} - {end_day:%d.%m.%Y}\n"
        f"Дитячі фільми відфільтровано.\n"
    )
    ratings_status = (
        "Рейтинги: увімкнено (TMDb/OMDb)." if ratings_enabled
        else "Рейтинги: вимкнено. Додай TMDB_API_KEY і OMDB_API_KEY у .env."
    )

    if not schedules:
        return header + f"{RATINGS_MARK} {ratings_status}\n\nНемає сеансів за обраними умовами."

    modern = [s for s in schedules if s.release_year is not None and s.release_year >= modern_year_threshold]
    retro = [s for s in schedules if s.release_year is not None and s.release_year < modern_year_threshold]
    unknown = [s for s in schedules if s.release_year is None]

    lines = [header]
    lines.append(f"{RATINGS_MARK} {ratings_status}")
    lines.append("")
    lines.append(f"Сучасні ({modern_year_threshold}+):")
    if modern:
        for film in modern:
            year = film.release_year if film.release_year is not None else "?"
            genres_text = ", ".join(film.genres) if film.genres else "невідомо"
            lines.append(f"{MOVIE_MARK} <b>{html.escape(film.title)}</b> ({year})")
            lines.append(f"  {GENRE_MARK} Жанр: {html.escape(genres_text)}")
            ratings_lines = format_ratings_lines(film.ratings)
            for rating_text in ratings_lines:
                lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
            if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
                lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
            lines.append(f"  {SESSIONS_MARK} {format_sessions_by_day(film)}")
            lines.append(FILM_SEPARATOR)
    else:
        lines.append("- Немає")

    lines.append("")
    lines.append("Ретро за десятиліттями:")
    if retro:
        by_decade: dict[int, list[FilmSchedule]] = {}
        for film in retro:
            decade = (film.release_year // 10) * 10  # type: ignore[operator]
            by_decade.setdefault(decade, []).append(film)

        for decade in sorted(by_decade.keys(), reverse=True):
            lines.append(f"{decade}-ті:")
            for film in sorted(by_decade[decade], key=lambda f: f.title):
                genres_text = ", ".join(film.genres) if film.genres else "невідомо"
                lines.append(f"{MOVIE_MARK} <b>{html.escape(film.title)}</b> ({film.release_year})")
                lines.append(f"  {GENRE_MARK} Жанр: {html.escape(genres_text)}")
                ratings_lines = format_ratings_lines(film.ratings)
                for rating_text in ratings_lines:
                    lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
                if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
                    lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
                lines.append(f"  {SESSIONS_MARK} {format_sessions_by_day(film)}")
                lines.append(FILM_SEPARATOR)
    else:
        lines.append("- Немає")

    if unknown:
        lines.append("")
        lines.append("Без року релізу:")
        for film in unknown:
            genres_text = ", ".join(film.genres) if film.genres else "невідомо"
            lines.append(f"{MOVIE_MARK} <b>{html.escape(film.title)}</b>")
            lines.append(f"  {GENRE_MARK} Жанр: {html.escape(genres_text)}")
            ratings_lines = format_ratings_lines(film.ratings)
            for rating_text in ratings_lines:
                lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
            if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
                lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
            lines.append(f"  {SESSIONS_MARK} {format_sessions_by_day(film)}")
            lines.append(FILM_SEPARATOR)

    return "\n".join(lines).strip()


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
) -> str:
    end_day = start_day + timedelta(days=days - 1)
    header = (
        f"Кіно: Warszawa Młociny\n"
        f"Період: {start_day:%d.%m.%Y} - {end_day:%d.%m.%Y}\n"
        f"Формат: тільки перелік фільмів (без сеансів).\n"
    )
    ratings_status = (
        "Рейтинги: увімкнено (TMDb/OMDb)." if ratings_enabled
        else "Рейтинги: вимкнено. Додай TMDB_API_KEY і OMDB_API_KEY у .env."
    )

    if not schedules:
        return header + f"{RATINGS_MARK} {ratings_status}\n\nНемає фільмів за обраними умовами."

    modern = [s for s in schedules if s.release_year is not None and s.release_year >= modern_year_threshold]
    retro = [s for s in schedules if s.release_year is not None and s.release_year < modern_year_threshold]
    unknown = [s for s in schedules if s.release_year is None]

    lines = [header]
    lines.append(f"{RATINGS_MARK} {ratings_status}")
    lines.append("")
    lines.append(f"Сучасні ({modern_year_threshold}+):")
    if modern:
        for film in modern:
            year = film.release_year if film.release_year is not None else "?"
            genres_text = ", ".join(film.genres) if film.genres else "невідомо"
            lines.append(f"{MOVIE_MARK} <b>{html.escape(film.title)}</b> ({year})")
            lines.append(f"  {GENRE_MARK} Жанр: {html.escape(genres_text)}")
            ratings_lines = format_ratings_lines(film.ratings)
            for rating_text in ratings_lines:
                lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
            if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
                lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
            lines.append(FILM_SEPARATOR)
    else:
        lines.append("- Немає")

    lines.append("")
    lines.append("Ретро за десятиліттями:")
    if retro:
        by_decade: dict[int, list[FilmSchedule]] = {}
        for film in retro:
            decade = (film.release_year // 10) * 10  # type: ignore[operator]
            by_decade.setdefault(decade, []).append(film)

        for decade in sorted(by_decade.keys(), reverse=True):
            lines.append(f"{decade}-ті:")
            for film in sorted(by_decade[decade], key=lambda f: f.title):
                genres_text = ", ".join(film.genres) if film.genres else "невідомо"
                lines.append(f"{MOVIE_MARK} <b>{html.escape(film.title)}</b> ({film.release_year})")
                lines.append(f"  {GENRE_MARK} Жанр: {html.escape(genres_text)}")
                ratings_lines = format_ratings_lines(film.ratings)
                for rating_text in ratings_lines:
                    lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
                if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
                    lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
                lines.append(FILM_SEPARATOR)
    else:
        lines.append("- Немає")

    if unknown:
        lines.append("")
        lines.append("Без року релізу:")
        for film in unknown:
            genres_text = ", ".join(film.genres) if film.genres else "невідомо"
            lines.append(f"{MOVIE_MARK} <b>{html.escape(film.title)}</b>")
            lines.append(f"  {GENRE_MARK} Жанр: {html.escape(genres_text)}")
            ratings_lines = format_ratings_lines(film.ratings)
            for rating_text in ratings_lines:
                lines.append(f"  {RATINGS_MARK} {html.escape(rating_text)}")
            if normalize_text(film.title).startswith("diabeł ubiera się u prady"):
                lines.append(f"  {html.escape(SPECIAL_PRADA_NOTE)}")
            lines.append(FILM_SEPARATOR)

    return "\n".join(lines).strip()


class TelegramBot:
    def __init__(
        self,
        token: str,
        kino_client: MultikinoClient,
        ratings_provider: RatingsProvider | None,
        timezone_name: str,
        modern_year_threshold: int,
        week_days: int,
    ) -> None:
        self.token = token
        self.kino_client = kino_client
        self.ratings_provider = ratings_provider
        self.tz = ZoneInfo(timezone_name)
        self.modern_year_threshold = modern_year_threshold
        self.week_days = week_days
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

    def run(self) -> None:
        logging.info("Telegram-бот запущено.")
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

    def _send_message(self, chat_id: int, text: str) -> None:
        for part in split_for_telegram(text):
            response = requests.post(
                f"{self.api_base}/sendMessage",
                json={"chat_id": chat_id, "text": part, "parse_mode": "HTML"},
                timeout=30,
            )
            response.raise_for_status()

    def _commands_text(self) -> str:
        return (
            "Доступні команди:\n"
            "/week - 7 днів, із сеансами\n"
            "/week_l - 7 днів, без сеансів\n"
            "/today - сьогодні, із сеансами\n"
            "/today_l - сьогодні, без сеансів\n"
            "/tomorrow - завтра, із сеансами\n"
            "/tomorrow_l - завтра, без сеансів\n"
            "/commands - список команд\n"
            "/help - підказка"
        )

    def _register_commands(self) -> None:
        try:
            response = requests.post(
                f"{self.api_base}/setMyCommands",
                json={"commands": BOT_COMMANDS},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logging.warning("Не вдалося оновити список команд бота: %s", payload)
        except Exception as exc:
            logging.warning("Не вдалося зареєструвати команди в Telegram: %s", exc)

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        command = extract_command(text)

        if command in {"/start", "/help"}:
            self._send_message(chat_id, "Привіт. Я бот для Multikino Warszawa Młociny.\n\n" + self._commands_text())
            return

        if command == "/commands":
            self._send_message(chat_id, self._commands_text())
            return

        if command == "/today":
            self._send_report(chat_id, days=1, list_only=False, start_offset_days=0)
            return

        if command == "/today_l":
            self._send_report(chat_id, days=1, list_only=True, start_offset_days=0)
            return

        if command == "/tomorrow":
            self._send_report(chat_id, days=1, list_only=False, start_offset_days=1)
            return

        if command == "/tomorrow_l":
            self._send_report(chat_id, days=1, list_only=True, start_offset_days=1)
            return

        if command == "/week":
            self._send_report(chat_id, days=self.week_days, list_only=False, start_offset_days=0)
            return

        if command == "/week_l":
            self._send_report(chat_id, days=self.week_days, list_only=True, start_offset_days=0)
            return

        self._send_message(
            chat_id,
            "Не зрозумів команду.\n\n" + self._commands_text(),
        )

    def _send_report(
        self,
        chat_id: int,
        days: int,
        list_only: bool = False,
        start_offset_days: int = 0,
    ) -> None:
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
                )
            else:
                report = format_week_report(
                    schedules=schedules,
                    start_day=start_day,
                    days=days,
                    modern_year_threshold=self.modern_year_threshold,
                    ratings_enabled=bool(self.ratings_provider and self.ratings_provider.enabled()),
                )
            self._send_message(chat_id, report)
        except Exception as exc:
            logging.exception("Не вдалося зібрати звіт: %s", exc)
            self._send_message(chat_id, "Не вдалося отримати розклад. Спробуй ще раз трохи пізніше.")


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
        }
    )
    client = MultikinoClient(session=session, cinema_slug=cinema_slug)
    client.initialize()
    return client


def run_print_week(
    client: MultikinoClient,
    ratings_provider: RatingsProvider | None,
    days: int,
    timezone_name: str,
    modern_year_threshold: int,
) -> None:
    start_day = datetime.now(ZoneInfo(timezone_name)).date()
    schedules = collect_week_schedule(client, start_day, days=days, ratings_provider=ratings_provider)
    report = format_week_report(
        schedules=schedules,
        start_day=start_day,
        days=days,
        modern_year_threshold=modern_year_threshold,
        ratings_enabled=bool(ratings_provider and ratings_provider.enabled()),
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
    args = parser.parse_args()

    timezone_name = os.getenv("BOT_TIMEZONE", "Europe/Warsaw")
    modern_year_threshold = read_env_int("MODERN_YEAR_THRESHOLD", 2010)
    week_days = read_env_int("WEEK_DAYS", 7)
    tmdb_api_key = os.getenv("TMDB_API_KEY", "").strip()
    omdb_api_key = os.getenv("OMDB_API_KEY", "").strip()

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
    )
    bot.run()


if __name__ == "__main__":
    main()
