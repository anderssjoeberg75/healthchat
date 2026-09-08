"""Shared FastAPI dependencies: the logged-in user and their workspace."""

from fastapi import Depends, HTTPException, Request, status

from . import auth, config
from .workspace import Workspace, get_workspace


def current_user(request: Request) -> dict:
    user = auth.resolve_session(request.cookies.get(config.SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inte inloggad")
    return user


def current_workspace(user: dict = Depends(current_user)) -> Workspace:
    return get_workspace(user["id"])
