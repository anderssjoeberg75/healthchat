# HealthChat Web — server

FastAPI backend plus a dependency-free single-page frontend. See the repository
[README](../README.md) for setup and configuration; this file documents the
internals.

## Layout

```
backend/
  config.py            Environment configuration and per-user paths
  auth.py              Accounts, PBKDF2 password hashing, server-side sessions
  deps.py              FastAPI dependencies (current user / current workspace)
  workspace.py         Per-user runtime state: config, database, handlers, chat
  charts.py            Headless Matplotlib figures (port of charts_view.py)
  metrics.py           Dashboard card values and activity rows
  chatsvc.py           Query classification and context building for the AI
  exporters.py         TXT / PDF / DOCX conversation export
  routers/             HTTP endpoints
frontend/
  index.html           The application shell (dashboard + chat panes)
  login.html           Login / registration
  static/app.js        All UI behaviour and dialogs
  static/styles.css    The desktop palette and layout, as CSS
```

## How the desktop app maps onto this

| Desktop (v4.0.4) | Web (v5.0.0) |
| --- | --- |
| One `HealthChatApp` instance | One `Workspace` per logged-in user |
| `~/.healthchat/` | `DATA_DIR/users/<id>/` |
| Tk canvases drawing Matplotlib | `GET /api/charts/*.png` rendering the same figures with Agg |
| `update_dashboard_cards()` | `GET /api/dashboard` → `metrics.dashboard_cards()` |
| `_process_message()` on a worker thread | `POST /api/chat` → `chatsvc.process_message()` |
| `perform_unified_checkin()` | `POST /api/checkin` + `GET /api/sync/status` polling |
| Toplevel dialogs | Modal overlays in `app.js` |
| Local callback HTTP server for OAuth | `GET /oauth/<service>/callback` |

Charts are rendered server-side on purpose: it reuses the desktop's plotting code
unchanged, so the dashboard looks identical rather than approximated by a
JavaScript charting library.

## API

| Method & path | Purpose |
| --- | --- |
| `GET /api/auth/status` · `POST /api/auth/{register,login,logout}` | Accounts |
| `POST /api/auth/password` · `POST /api/auth/delete-account` | Profile page actions |
| `GET/POST /api/settings` · `GET /api/settings/models` | Configuration |
| `GET /api/dashboard` · `GET /api/charts/{weekly,trends,evolab}.png` | Dashboard |
| `GET /api/status` · `POST /api/garmin/connect` · `POST /api/garmin/mfa` | Garmin connection |
| `POST /api/checkin` · `GET /api/sync/status` · `POST /api/refresh` | Synchronisation |
| `POST /api/import/{fitbit,strava,withings}` | Import an official export file |
| `GET/POST /api/chat` · `POST /api/chat/reset` | Conversation |
| `GET/POST/PUT/DELETE /api/chats[/{id}]` · `GET /api/search` · `POST /api/export` | History |
| `GET/POST /api/quick-questions` · `GET/POST/PUT/DELETE /api/prompts` | Prompts |
| `GET /api/connect/{service}/url` · `GET /oauth/{service}/callback` | OAuth |

Interactive documentation is served at `/api/docs`.

## Tests

```bash
python -m pytest tests/test_webapp_api.py tests/test_webapp_charts.py tests/test_webapp_chatsvc.py
```

No test performs a network call — Garmin, the AI providers and the OAuth
exchanges are never contacted.
