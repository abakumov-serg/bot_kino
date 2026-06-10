# Bot Kino - Technical Roadmap

## 1. Purpose

Telegram bot for Multikino (Warszawa Mlociny) that:
- shows schedule for today / tomorrow / week;
- filters kids movies;
- groups films into modern vs retro;
- supports localized interface (`uk`, `pl`, `en`, with `ru -> uk`);
- can enrich movies with TMDb/OMDb ratings.

## 2. Current Baseline (Done)

- Core commands: `/today`, `/today_l`, `/tomorrow`, `/tomorrow_l`, `/week`, `/week_l`, `/commands`, `/help`.
- `_l` commands return movies list without sessions.
- Movie formatting with markers and separators.
- Filtering of kids/family content.
- Release-year enrichment and retro grouping by decades.
- Ratings integration (TMDb + OMDb), including genre/year correction fallback.
- Telegram command menu registration via `setMyCommands`.
- Telegram updates can run via polling or webhook.
- Dockerized deployment and server-side deploy script.
- Local-to-remote deploy helper script.
- Locale-aware command/help responses with auto-detection by Telegram language code.

## 3. Product Requirements

### 3.1 User-facing behavior

1. Bot must respond within acceptable time for each command.
2. `/commands` should list only command reference.
3. `/help` should explain bot purpose and locale behavior (without duplicating full command list).
4. Locale should be auto-detected when enabled (`BOT_LOCALE_AUTO=1`) and fallback to `BOT_LOCALE`.
5. If Multikino access is blocked, bot should return clear user message instead of crashing.

### 3.2 Data quality

1. Session times should match provider data.
2. Movie year and genre should be corrected when provider metadata is inconsistent.
3. Ratings should be optional and degrade gracefully when API keys are absent.

## 4. Architecture & Config

### 4.1 Runtime components

- Python Telegram worker (`bot.py`)
- External APIs:
  - Multikino endpoints
  - Telegram Bot API
  - TMDb API (optional)
  - OMDb API (optional)

### 4.2 Key environment variables

- `TELEGRAM_BOT_TOKEN`
- `MULTIKINO_CINEMA_SLUG`
- `MULTIKINO_CINEMA_ID`
- `MULTIKINO_PROXY_URL`
- `MULTIKINO_PROXY_INSECURE`
- `MULTIKINO_PROXY_CA_BUNDLE`
- `BOT_LOCALE`
- `BOT_LOCALE_AUTO`
- `BOT_CINEMA_LABEL`
- `BOT_TIMEZONE`
- `WEEK_DAYS`
- `MODERN_YEAR_THRESHOLD`
- `TELEGRAM_UPDATE_MODE`
- `TELEGRAM_WEBHOOK_URL`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_WEBHOOK_LISTEN_HOST`
- `TELEGRAM_WEBHOOK_LISTEN_PORT`
- `TELEGRAM_WEBHOOK_PORT`
- `TELEGRAM_WEBHOOK_CERT_FILE`
- `TELEGRAM_WEBHOOK_KEY_FILE`
- `TELEGRAM_WEBHOOK_UPLOAD_CERT`
- `TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES`
- `TELEGRAM_WEBHOOK_MAX_CONNECTIONS`
- `TELEGRAM_WEBHOOK_IP_ADDRESS`
- `TMDB_API_KEY`
- `OMDB_API_KEY`

## 5. Delivery Plan

### Milestone A - Reliability Hardening

1. Add retry/backoff strategy for transient network errors.
2. Add timeout guards around all third-party calls.
3. Improve proxy diagnostics in logs (connection/auth/challenge classes).
4. Add startup self-check for critical configuration.

**Acceptance criteria:**
- bot does not crash-loop on upstream 4xx/5xx/proxy errors;
- user receives meaningful fallback message;
- logs are actionable.

### Milestone B - Data Accuracy

1. Add deterministic tie-break rules for title/year matching.
2. Cache rating/provider responses with TTL.
3. Add optional mismatch report mode for sessions vs metadata.

**Acceptance criteria:**
- reduced wrong-year/wrong-genre occurrences;
- lower external API traffic and faster response.

### Milestone C - UX & Commands

1. Keep `/commands` minimal and stable.
2. Extend `/help` with concise examples for key commands.
3. Add command-level localized hints for list mode (`_l`) vs full mode.

**Acceptance criteria:**
- clearer onboarding;
- fewer user mistakes when choosing command type.

### Milestone D - Ops & Deployment

1. Keep webhook health endpoint stable (`/healthz`).
2. Add rolling deploy notes and rollback checklist.
3. Add post-deploy smoke test script (`/today_l`, `/help`, `/commands`).

**Acceptance criteria:**
- predictable deploy flow;
- faster recovery after bad release.

## 6. Risks & Mitigations

1. **Cloudflare / anti-bot restrictions**
   - Mitigation: configurable proxy, explicit blocked-state messaging, alternate egress strategy.
2. **Third-party API instability**
   - Mitigation: retries, cache, graceful degradation.
3. **Locale ambiguity**
   - Mitigation: explicit fallback policy and configurable auto-locale switch.

## 7. Test Strategy

### 7.1 Functional

- Command routing tests for all command variants.
- Locale resolution tests (`uk/pl/en`, `ru -> uk`, fallback behavior).
- Report formatting tests (full vs list-only).

### 7.2 Integration

- Mocked Multikino/Telegram/TMDb/OMDb responses.
- Proxy-enabled network scenario tests.

### 7.3 Smoke

- Manual run in container:
  - `/commands`
  - `/help`
  - `/today_l`
  - `/today`

## 8. Definition of Done

Feature/change is considered done when:
1. code is merged to `main`;
2. container build succeeds;
3. smoke commands pass in deployed environment;
4. logs contain no unhandled exception loops;
5. docs/config examples are updated.
