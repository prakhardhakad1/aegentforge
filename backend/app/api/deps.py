"""Shared FastAPI dependencies: DB session + optional X-API-Key auth.

Auth contract (docs/INTERFACES.md): the ``X-API-Key`` header is checked ONLY
when the ``API_KEY`` env var is set; otherwise the app runs in guest mode and
no auth is required.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.base import get_session_factory

logger = logging.getLogger("agentforge.auth")


def get_db() -> Iterator[Session]:
    """Yield a request-scoped SQLAlchemy session."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def require_api_key(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    """Enforce the optional ``X-API-Key`` contract for HTTP routes.

    - ``API_KEY`` unset/empty -> guest mode: always allowed.
    - ``API_KEY`` set -> header must match exactly, else 401.
    """
    if not settings.auth_enabled:
        return
    provided = request.headers.get("x-api-key")
    if provided and provided == settings.api_key:
        return
    logger.warning("Rejected request to %s: missing/invalid API key", request.url.path)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid X-API-Key header",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def check_ws_auth(websocket: Any, settings: Settings) -> bool:
    """Auth check for the WebSocket route (cannot use Request-based deps).

    Browsers cannot set custom headers on WebSocket handshakes, so the key may
    be provided via the ``X-API-Key`` header OR an ``api_key`` query parameter.
    Returns True when allowed; when not allowed the caller should close the
    socket with code 4401.
    """
    if not settings.auth_enabled:
        return True
    header_key = websocket.headers.get("x-api-key")
    if header_key and header_key == settings.api_key:
        return True
    query_key = websocket.query_params.get("api_key") or websocket.query_params.get("token")
    if query_key and query_key == settings.api_key:
        return True
    return False
