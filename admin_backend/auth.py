from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status

from .config import Settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def verify_password(settings: Settings, password: str) -> bool:
    if settings.admin_password_hash:
        try:
            import bcrypt
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="bcrypt is required when MEDIWRITER_ADMIN_PASSWORD_HASH is set",
            ) from exc
        return bool(
            bcrypt.checkpw(
                password.encode("utf-8"),
                settings.admin_password_hash.encode("utf-8"),
            )
        )
    return hmac.compare_digest(password, settings.admin_password)


def create_session_token(settings: Settings, username: str) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + settings.session_ttl_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_part = _b64(payload_bytes)
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_part}.{_b64(signature)}"


def read_session_token(settings: Settings, token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload_part, signature_part = token.split(".", 1)
    expected = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual = _unb64(signature_part)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload = json.loads(_unb64(payload_part).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def set_session_cookie(settings: Settings, response: Response, username: str) -> None:
    response.set_cookie(
        settings.session_cookie,
        create_session_token(settings, username),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_ttl_seconds,
        path="/",
    )


def clear_session_cookie(settings: Settings, response: Response) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


def require_admin(request: Request) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    payload = read_session_token(settings, request.cookies.get(settings.session_cookie))
    if not payload or payload.get("sub") != settings.admin_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return {"username": settings.admin_user}


AdminUser = Depends(require_admin)

