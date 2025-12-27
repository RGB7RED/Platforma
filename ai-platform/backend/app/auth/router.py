from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .schemas import LoginRequest, LogoutResponse, MeResponse, RefreshResponse, RegisterRequest, TokenResponse, UserResponse
from .security import (
    create_access_token,
    generate_refresh_token,
    get_user_from_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from .settings import get_auth_settings
from .. import db

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def _ensure_auth_enabled() -> None:
    settings = get_auth_settings()
    if settings.mode == "apikey":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Auth mode disabled")
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_JWT_SECRET is not configured",
        )
    if not settings.refresh_hash_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_REFRESH_TOKEN_SECRET is not configured",
        )


def _ensure_db_ready() -> None:
    if not db.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth requires database persistence",
        )


def _refresh_cookie_settings() -> Dict[str, object]:
    settings = get_auth_settings()
    return {
        "key": settings.refresh_cookie_name,
        "httponly": True,
        "secure": settings.refresh_cookie_secure,
        "samesite": settings.refresh_cookie_samesite,
        "path": settings.refresh_cookie_path,
        "domain": settings.refresh_cookie_domain,
    }


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    cookie = _refresh_cookie_settings()
    response.set_cookie(
        key=cookie["key"],
        value=token,
        expires=expires_at,
        max_age=int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        httponly=cookie["httponly"],
        secure=cookie["secure"],
        samesite=cookie["samesite"],
        path=cookie["path"],
        domain=cookie["domain"],
    )


def _clear_refresh_cookie(response: Response) -> None:
    cookie = _refresh_cookie_settings()
    response.delete_cookie(
        key=cookie["key"],
        path=cookie["path"],
        domain=cookie["domain"],
    )


def _normalize_user(user: Dict[str, object]) -> UserResponse:
    return UserResponse(id=str(user["id"]), email=user["email"])


def _access_token_response(user: Dict[str, object]) -> TokenResponse:
    settings = get_auth_settings()
    access_token = create_access_token(user_id=str(user["id"]), email=user["email"])
    expires_in = int(timedelta(minutes=settings.access_ttl_minutes).total_seconds())
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=_normalize_user(user),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Dict[str, object]:
    settings = get_auth_settings()
    if settings.mode == "apikey":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth mode disabled")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    user = await get_user_from_access_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    return user


@router.post("/register", response_model=TokenResponse)
async def register(payload: RegisterRequest, request: Request, response: Response) -> TokenResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    email = payload.email.strip().lower()
    existing = await db.get_auth_user_by_email(email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    password_hash = hash_password(payload.password)
    user = await db.create_auth_user(email=email, password_hash=password_hash)

    refresh_token = generate_refresh_token()
    refresh_hash = hash_refresh_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=get_auth_settings().refresh_ttl_days)
    await db.create_refresh_session(
        user_id=str(user["id"]),
        token_hash=refresh_hash,
        expires_at=expires_at,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_refresh_cookie(response, refresh_token, expires_at)
    return _access_token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> TokenResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    email = payload.email.strip().lower()
    user = await db.get_auth_user_by_email(email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    refresh_token = generate_refresh_token()
    refresh_hash = hash_refresh_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=get_auth_settings().refresh_ttl_days)
    await db.create_refresh_session(
        user_id=str(user["id"]),
        token_hash=refresh_hash,
        expires_at=expires_at,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_refresh_cookie(response, refresh_token, expires_at)
    return _access_token_response(user)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(request: Request, response: Response) -> RefreshResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    settings = get_auth_settings()
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    token_hash = hash_refresh_token(raw_token)
    session = await db.get_refresh_session_by_hash(token_hash)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if session.get("revoked_at") is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")
    expires_at = session.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = await db.get_auth_user_by_id(str(session["user_id"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_refresh_token = generate_refresh_token()
    new_refresh_hash = hash_refresh_token(new_refresh_token)
    new_expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_ttl_days)
    rotated = await db.rotate_refresh_session(
        session_id=str(session["id"]),
        token_hash=new_refresh_hash,
        expires_at=new_expires_at,
    )
    if not rotated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    _set_refresh_cookie(response, new_refresh_token, new_expires_at)
    token_response = _access_token_response(user)
    return RefreshResponse(
        access_token=token_response.access_token,
        token_type=token_response.token_type,
        expires_in=token_response.expires_in,
        user=token_response.user,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response) -> LogoutResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    settings = get_auth_settings()
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        token_hash = hash_refresh_token(raw_token)
        session = await db.get_refresh_session_by_hash(token_hash)
        if session:
            await db.revoke_refresh_session(session_id=str(session["id"]))
    _clear_refresh_cookie(response)
    return LogoutResponse(detail="Logged out")


@router.get("/me", response_model=MeResponse)
async def me(user: Dict[str, object] = Depends(get_current_user)) -> MeResponse:
    _ensure_auth_enabled()
    return MeResponse(user=_normalize_user(user))
