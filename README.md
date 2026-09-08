# HealthChat v5.0.0 (Web)

**AI-Powered Insights for Your Garmin Connect Fitness Data — now in the browser**

HealthChat lets you explore your Garmin, Fitbit, Withings and Strava data through
natural-language conversation, with a dashboard of trends and analytics alongside
the chat. Version 5 is the same application as HealthChat Desktop v4.0.4 — same
layout, same charts, same features — served from a web address instead of an
`.exe` on the desktop.

The desktop version is archived in
[`HealthChatDesktop-v4.0.4-legacy.zip`](HealthChatDesktop-v4.0.4-legacy.zip) in
this repository root.

## Why a web app

- **The database is never exposed to the internet.** Each user's SQLite database
  lives on the server, next to the app; nothing has to be reachable from outside.
- **Simpler access for users.** A URL and a login instead of an installer,
  Windows-only builds, code signing and per-machine updates.
- **Multi-user by design.** Accounts are isolated: separate database, separate
  configuration, separate API keys, separate OAuth tokens, separate chat history.
- **The AI can work more autonomously.** The server runs around the clock, so
  scheduled syncs and background analysis no longer require the user's computer
  to be switched on (see the W-track in [board.md](board.md)).

## Features

Unchanged from the desktop build:

- 💬 **Natural-language queries** about your fitness data, in Swedish or English
- 🤖 **Six AI providers** — Ollama (local), xAI (Grok), OpenAI, Google Gemini,
  Anthropic (Claude) and Azure OpenAI
- 📊 **Dashboard, EvoLab and activity log** — the same Matplotlib charts as the
  desktop app, rendered server-side
- 📥 **Check-in** across Garmin, Fitbit, Withings and Strava, plus a full
  historical sync
- 🔥 **Daily calorie-burn estimate** from BMR, steps and workouts
- 📝 **Saved prompts, quick questions, chat history, search** and PDF/DOCX/TXT export
- 🎨 **Light and dark mode**, same Fluent-style palette

## Quick start

```bash
pip install -r requirements.txt -r webapp/requirements.txt
uvicorn webapp.backend.main:app --reload
```

Open <http://localhost:8000>, create an account, then open **Settings** to fill in
your Garmin credentials and an AI provider key.

With Docker:

```bash
cp webapp/.env.example webapp/.env      # adjust HEALTHCHAT_BASE_URL first
docker compose -f webapp/docker-compose.yml up -d --build
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `HEALTHCHAT_DATA_DIR` | `./data` | Where accounts, per-user databases and tokens are stored |
| `HEALTHCHAT_BASE_URL` | `http://localhost:8000` | Public URL; OAuth redirect URIs are built from it |
| `HEALTHCHAT_SECRET_KEY` | auto-generated | Session signing secret (persisted in the data directory) |
| `HEALTHCHAT_DISABLE_REGISTRATION` | `0` | `1` = only the first account may be created |
| `HEALTHCHAT_COOKIE_SECURE` | `0` | `1` = session cookie is HTTPS-only (set this in production) |
| `HEALTHCHAT_SESSION_TTL_DAYS` | `30` | How long a login stays valid |

OAuth apps for Fitbit, Strava and Withings must use the redirect URI
`<HEALTHCHAT_BASE_URL>/oauth/<service>/callback`.

## Repository layout

```
ai_client.py            AI provider abstraction (shared with the desktop build)
garmin_db.py            SQLite schema and queries
garmin_handler.py       Garmin Connect authentication and data
fitbit_handler.py       Fitbit OAuth + sync
strava_handler.py       Strava OAuth + sync
withings_handler.py     Withings OAuth + weight/body composition
calorie_calc.py         BMR and daily burn estimate
webapp/backend/         FastAPI server (auth, per-user workspaces, charts, chat)
webapp/frontend/        Single-page UI (no build step)
tests/                  pytest suite for core modules and the web API
board.md                Task board, including the desktop → web migration plan
```

## Privacy & security

- Health data is stored in a per-user SQLite database on **your** server; the
  database is never exposed to the internet.
- Passwords are hashed with PBKDF2-HMAC-SHA256 (240 000 rounds, per-user salt).
- API keys and provider secrets are stored server-side and are never sent back to
  the browser — the UI only sees whether a value is set.
- Sessions are opaque tokens in an HTTP-only cookie; changing a password signs
  out every device.
- Deleting your account removes the account row and its entire data directory.
- With Ollama as the provider, no health data leaves your own network at all.

## Ollama

See [OLLAMA_SETUP_GUIDE.md](OLLAMA_SETUP_GUIDE.md). Point
`ollama_base_url` in Settings at the Ollama host that the *server* can reach
(for example `http://ollama:11434/v1` in Docker).

## Development

```bash
pip install -r requirements.txt -r webapp/requirements.txt -r requirements-dev.txt
python -m pytest
```

## License

See [LICENSE.txt](LICENSE.txt).
