"""OAuth connection flows for Fitbit, Strava and Withings.

On the desktop each dialog spun up a throwaway HTTP server on localhost to catch
the redirect. On the web the redirect lands on a real route of this app, so the
provider apps only need one stable redirect URI:
``<BASE_URL>/oauth/<provider>/callback``.
"""

import logging
import secrets
import sys
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import auth, config
from ..deps import current_workspace
from ..workspace import Workspace, get_workspace

sys.path.insert(0, str(config.PROJECT_ROOT))
from withings_handler import WithingsDataHandler  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(tags=["oauth"])

PROVIDERS = ("fitbit", "strava", "withings")

# One-shot CSRF states: state token -> user id.
_pending_states: Dict[str, int] = {}


def redirect_uri(provider: str) -> str:
    return f"{config.BASE_URL}/oauth/{provider}/callback"


def _result_page(title: str, message: str, colour: str) -> HTMLResponse:
    """The same confirmation page the desktop callback server served."""
    return HTMLResponse(
        f"""
        <html>
        <head><meta charset="utf-8"><title>HealthChat</title></head>
        <body style="font-family: Segoe UI, sans-serif; text-align: center; padding-top: 50px; background: #F3F4F6;">
            <div style="background: white; max-width: 500px; margin: 0 auto; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h2 style="color: {colour}; margin-bottom: 10px;">{title}</h2>
                <p style="color: #4B5563; font-size: 16px;">{message}</p>
                <p style="color: #6B7280; font-size: 14px;"><a href="/" style="color:#0078D4;">Tillbaka till HealthChat</a></p>
            </div>
        </body>
        </html>
        """
    )


@router.get("/api/connect/{provider}/url")
def connect_url(provider: str, workspace: Workspace = Depends(current_workspace)):
    """Build the provider's authorization URL for this user."""
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Okänd tjänst.")

    client_id = (workspace.config.get(f"{provider}_client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="Fyll i ditt Client ID först innan du klickar på inloggning.")

    state = secrets.token_urlsafe(24)
    _pending_states[state] = workspace.user_id

    if provider == "fitbit":
        url = workspace.fitbit_handler.get_auth_url(client_id, redirect_uri("fitbit")) + f"&state={state}"
    elif provider == "strava":
        url = workspace.strava_handler.get_auth_url(client_id, redirect_uri("strava")) + f"&state={state}"
    else:
        url = WithingsDataHandler.get_auth_url(client_id, redirect_uri("withings")).replace(
            "state=withings_state", f"state={state}"
        )

    return {"url": url, "redirect_uri": redirect_uri(provider)}


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, request: Request):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Okänd tjänst.")

    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    if not code:
        return _result_page("Ingen kod mottogs", "Auktoriseringen avbröts.", "#EF4444")

    # Resolve the user from the one-shot state, falling back to the session cookie.
    user_id = _pending_states.pop(state, None)
    if user_id is None:
        user = auth.resolve_session(request.cookies.get(config.SESSION_COOKIE))
        if not user:
            return _result_page("Sessionen har gått ut", "Logga in i HealthChat och försök igen.", "#EF4444")
        user_id = user["id"]

    workspace = get_workspace(user_id)
    client_id = (workspace.config.get(f"{provider}_client_id") or "").strip()
    client_secret = (workspace.config.get(f"{provider}_client_secret") or "").strip()

    try:
        if provider == "fitbit":
            workspace.fitbit_handler.exchange_code_for_token(
                code, client_id, client_secret, redirect_uri("fitbit")
            )
            return _result_page(
                "✅ Fitbit Ansluten!",
                "Ditt Fitbit-konto har anslutits framgångsrikt till HealthChat.",
                "#10B981",
            )

        if provider == "strava":
            workspace.strava_handler.exchange_code_for_token(
                code, client_id, client_secret, redirect_uri("strava")
            )
            return _result_page(
                "✅ Strava Ansluten!",
                "Ditt Strava-konto har anslutits framgångsrikt till HealthChat.",
                "#FC4C02",
            )

        handler = WithingsDataHandler(
            client_id=client_id, client_secret=client_secret, refresh_token="", db=workspace.db
        )
        result = handler.exchange_code_for_token(code, client_id, client_secret, redirect_uri("withings"))
        workspace.config["withings_access_token"] = result.get("access_token", "")
        workspace.config["withings_refresh_token"] = result.get("refresh_token", "")
        workspace.save_config()
        return _result_page(
            "✅ Withings Ansluten!",
            "Ditt Withings-konto har anslutits framgångsrikt till HealthChat.",
            "#10B981",
        )

    except Exception as exc:
        logger.error("%s OAuth exchange failed: %s", provider, exc)
        return _result_page(f"❌ Kunde inte ansluta till {provider.capitalize()}", str(exc), "#EF4444")


@router.post("/api/connect/{provider}/disconnect")
def disconnect(provider: str, workspace: Workspace = Depends(current_workspace)):
    """Forget the stored tokens for one source."""
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Okänd tjänst.")

    if provider == "withings":
        workspace.config["withings_access_token"] = ""
        workspace.config["withings_refresh_token"] = ""
        workspace.save_config()
    else:
        handler = workspace.fitbit_handler if provider == "fitbit" else workspace.strava_handler
        handler.access_token = ""
        handler.refresh_token = ""
        token_file = getattr(handler, "token_file", None)
        if token_file and token_file.exists():
            token_file.unlink()

    return {"ok": True, "sources": workspace.connected_sources()}
