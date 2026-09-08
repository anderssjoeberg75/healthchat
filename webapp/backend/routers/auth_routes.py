"""Registration, login, logout and account management."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from .. import auth, config
from ..deps import current_user
from ..workspace import drop_workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str
    display_name: str = ""


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AccountDeletion(BaseModel):
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )


@router.get("/status")
def status_endpoint(request: Request):
    """Who is logged in, and is self-service registration open?"""
    user = auth.resolve_session(request.cookies.get(config.SESSION_COOKIE))
    return {
        "authenticated": bool(user),
        "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]} if user else None,
        "registration_open": not config.REGISTRATION_DISABLED or auth.user_count() == 0,
        "version": config.APP_VERSION,
    }


@router.post("/register")
def register(credentials: Credentials, response: Response):
    # The very first account can always be created, so a fresh deployment is usable.
    if config.REGISTRATION_DISABLED and auth.user_count() > 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registrering är avstängd.")
    try:
        user = auth.create_user(credentials.email, credentials.password, credentials.display_name)
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _set_session_cookie(response, auth.create_session(user["id"]))
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}


@router.post("/login")
def login(credentials: Credentials, response: Response):
    try:
        user = auth.authenticate(credentials.email, credentials.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _set_session_cookie(response, auth.create_session(user["id"]))
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.destroy_session(request.cookies.get(config.SESSION_COOKIE))
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/password")
def change_password(payload: PasswordChange, response: Response, user: dict = Depends(current_user)):
    try:
        auth.change_password(user["id"], payload.current_password, payload.new_password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Every session was invalidated, including this one.
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return {"ok": True, "message": "Lösenordet är ändrat. Logga in igen."}


@router.post("/delete-account")
def delete_account(payload: AccountDeletion, response: Response, user: dict = Depends(current_user)):
    if not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fel lösenord.")
    drop_workspace(user["id"])
    auth.delete_user(user["id"])
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return {"ok": True}
