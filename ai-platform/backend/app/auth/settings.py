from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
import os


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    jwt_secret: str
    jwt_algorithm: str
    access_ttl_minutes: int
    refresh_ttl_days: int
    refresh_cookie_name: str
    refresh_cookie_path: str
    refresh_cookie_domain: Optional[str]
    refresh_cookie_secure: bool
    refresh_cookie_samesite: str
    issuer: Optional[str]
    audience: Optional[str]
    refresh_hash_secret: str


@lru_cache
def get_auth_settings() -> AuthSettings:
    mode = os.getenv("AUTH_MODE", "apikey").lower()
    jwt_secret = os.getenv("AUTH_JWT_SECRET", "")
    jwt_algorithm = os.getenv("AUTH_JWT_ALGORITHM", "HS256")
    access_ttl_minutes = int(os.getenv("AUTH_ACCESS_TOKEN_TTL_MINUTES", "15"))
    refresh_ttl_days = int(os.getenv("AUTH_REFRESH_TOKEN_TTL_DAYS", "30"))
    refresh_cookie_name = os.getenv("AUTH_REFRESH_COOKIE_NAME", "refresh_token")
    refresh_cookie_path = os.getenv("AUTH_REFRESH_COOKIE_PATH", "/auth")
    refresh_cookie_domain = os.getenv("AUTH_REFRESH_COOKIE_DOMAIN")
    refresh_cookie_samesite = os.getenv("AUTH_REFRESH_COOKIE_SAMESITE", "lax")
    refresh_hash_secret = os.getenv("AUTH_REFRESH_TOKEN_SECRET") or jwt_secret
    environment = os.getenv("ENVIRONMENT", "").lower()
    refresh_cookie_secure = environment == "production"
    issuer = os.getenv("AUTH_JWT_ISSUER")
    audience = os.getenv("AUTH_JWT_AUDIENCE")

    return AuthSettings(
        mode=mode,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        access_ttl_minutes=access_ttl_minutes,
        refresh_ttl_days=refresh_ttl_days,
        refresh_cookie_name=refresh_cookie_name,
        refresh_cookie_path=refresh_cookie_path,
        refresh_cookie_domain=refresh_cookie_domain,
        refresh_cookie_secure=refresh_cookie_secure,
        refresh_cookie_samesite=refresh_cookie_samesite,
        issuer=issuer,
        audience=audience,
        refresh_hash_secret=refresh_hash_secret,
    )
