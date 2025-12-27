from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from .settings import get_auth_settings
from .. import db

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(*, user_id: str, email: str) -> str:
    settings = get_auth_settings()
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_JWT_SECRET is not configured",
        )
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_ttl_minutes)
    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if settings.issuer:
        payload["iss"] = settings.issuer
    if settings.audience:
        payload["aud"] = settings.audience
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    settings = get_auth_settings()
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_JWT_SECRET is not configured",
        )
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    settings = get_auth_settings()
    if not settings.refresh_hash_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_REFRESH_TOKEN_SECRET is not configured",
        )
    digest = hmac.new(
        settings.refresh_hash_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def generate_action_token() -> str:
    return secrets.token_urlsafe(48)


def hash_action_token(token: str) -> str:
    settings = get_auth_settings()
    if not settings.action_token_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_ACTION_TOKEN_SECRET is not configured",
        )
    digest = hmac.new(
        settings.action_token_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


async def get_user_from_access_token(token: str) -> Optional[Dict[str, Any]]:
    if not db.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth requires database persistence",
        )
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        return None
    return await db.get_auth_user_by_id(user_id)
