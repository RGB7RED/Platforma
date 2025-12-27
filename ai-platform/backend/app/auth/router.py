from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Dict, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import RedirectResponse

from .email import build_public_link, get_email_settings, send_email
from .schemas import (
    DetailResponse,
    EmailRequest,
    LoginRequest,
    LogoutResponse,
    MeResponse,
    RefreshResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from .security import (
    create_access_token,
    generate_action_token,
    generate_refresh_token,
    get_user_from_access_token,
    hash_action_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from .settings import get_auth_settings, get_google_oauth_settings
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
    return UserResponse(
        id=str(user["id"]),
        email=user["email"],
        email_verified=user.get("email_verified_at") is not None,
    )


def _ensure_google_oauth_configured() -> None:
    settings = get_google_oauth_settings()
    if not settings.client_id or not settings.client_secret or not settings.redirect_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured",
        )


def _google_cookie_settings() -> Dict[str, object]:
    settings = get_auth_settings()
    return {
        "httponly": True,
        "secure": settings.refresh_cookie_secure,
        "samesite": "lax",
        "path": "/auth/google",
    }


def _safe_return_to(return_to: Optional[str], request: Request) -> str:
    default_path = "/app"
    if not return_to:
        return default_path
    parsed = urlparse(return_to)
    if not parsed.scheme and not parsed.netloc:
        return return_to if return_to.startswith("/") else default_path

    allowed_hosts = {request.url.netloc}
    public_base = get_email_settings().public_base_url
    if public_base:
        allowed_hosts.add(urlparse(public_base).netloc)
    if parsed.netloc in allowed_hosts:
        return return_to
    return default_path


def _build_oauth_redirect(return_to: str, token: TokenResponse) -> str:
    parsed = urlparse(return_to)
    fragment = urlencode(
        {
            "access_token": token.access_token,
            "expires_in": token.expires_in,
            "token_type": token.token_type,
        }
    )
    updated = parsed._replace(fragment=fragment)
    return urlunparse(updated)


def _access_token_response(user: Dict[str, object]) -> TokenResponse:
    settings = get_auth_settings()
    access_token = create_access_token(user_id=str(user["id"]), email=user["email"])
    expires_in = int(timedelta(minutes=settings.access_ttl_minutes).total_seconds())
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=_normalize_user(user),
    )


async def _issue_refresh_session(
    *,
    user: Dict[str, object],
    request: Request,
    response: Response,
) -> TokenResponse:
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

    return await _issue_refresh_session(user=user, request=request, response=response)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> TokenResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    email = payload.email.strip().lower()
    user = await db.get_auth_user_by_email(email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return await _issue_refresh_session(user=user, request=request, response=response)


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


@router.get("/google/login")
async def google_login(request: Request, return_to: Optional[str] = None) -> RedirectResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    _ensure_google_oauth_configured()
    settings = get_google_oauth_settings()
    state = secrets.token_urlsafe(32)
    safe_return_to = _safe_return_to(return_to, request)
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    response = RedirectResponse(url=auth_url)
    cookie = _google_cookie_settings()
    response.set_cookie(
        key="google_oauth_state",
        value=state,
        max_age=300,
        httponly=cookie["httponly"],
        secure=cookie["secure"],
        samesite=cookie["samesite"],
        path=cookie["path"],
    )
    response.set_cookie(
        key="google_oauth_return_to",
        value=safe_return_to,
        max_age=300,
        httponly=cookie["httponly"],
        secure=cookie["secure"],
        samesite=cookie["samesite"],
        path=cookie["path"],
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
) -> Response:
    _ensure_auth_enabled()
    _ensure_db_ready()
    _ensure_google_oauth_configured()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code")
    cookie_state = request.cookies.get("google_oauth_state")
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    settings = get_google_oauth_settings()
    token_payload = {
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "code": code,
        "redirect_uri": settings.redirect_url,
        "grant_type": "authorization_code",
    }

    try:
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data=token_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Google OAuth token response missing access token",
                )
            userinfo_response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_response.raise_for_status()
            profile = userinfo_response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to authenticate with Google",
        ) from exc

    email = profile.get("email")
    email_verified = profile.get("email_verified")
    provider_account_id = profile.get("sub")
    if not email or not provider_account_id or not email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account email is not verified",
        )

    oauth_account = await db.get_oauth_account(
        provider="google",
        provider_account_id=provider_account_id,
    )
    user = None
    if oauth_account:
        user = await db.get_auth_user_by_id(str(oauth_account["user_id"]))

    if not user:
        normalized_email = email.strip().lower()
        user = await db.get_auth_user_by_email(normalized_email)
        if not user:
            random_password = secrets.token_urlsafe(32)
            password_hash = hash_password(random_password)
            user = await db.create_auth_user(email=normalized_email, password_hash=password_hash)
        if user.get("email_verified_at") is None:
            verified_user = await db.mark_auth_user_email_verified(user_id=str(user["id"]))
            if verified_user:
                user = verified_user

    await db.upsert_oauth_account(
        provider="google",
        provider_account_id=provider_account_id,
        user_id=str(user["id"]),
        email=email,
    )

    cookie = _google_cookie_settings()
    return_to_cookie = request.cookies.get("google_oauth_return_to")
    safe_return_to = _safe_return_to(return_to_cookie, request) if return_to_cookie else None
    if safe_return_to:
        redirect_response = RedirectResponse(url=safe_return_to)
        token_response = await _issue_refresh_session(
            user=user,
            request=request,
            response=redirect_response,
        )
        redirect_url = _build_oauth_redirect(safe_return_to, token_response)
        redirect_response.headers["Location"] = redirect_url
        redirect_response.delete_cookie(key="google_oauth_state", path=cookie["path"])
        redirect_response.delete_cookie(key="google_oauth_return_to", path=cookie["path"])
        return redirect_response

    token_response = await _issue_refresh_session(user=user, request=request, response=response)
    response.delete_cookie(key="google_oauth_state", path=cookie["path"])
    response.delete_cookie(key="google_oauth_return_to", path=cookie["path"])
    return token_response


@router.post("/request-email-verify", response_model=DetailResponse)
async def request_email_verify(payload: EmailRequest) -> DetailResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    email = payload.email.strip().lower()
    user = await db.get_auth_user_by_email(email)
    if not user or user.get("email_verified_at") is not None:
        return DetailResponse(detail="If the account exists, a verification email was sent.")

    raw_token = generate_action_token()
    token_hash = hash_action_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=get_auth_settings().email_verify_ttl_hours)
    await db.create_email_verify_token(
        user_id=str(user["id"]),
        token_hash=token_hash,
        expires_at=expires_at,
    )
    verify_link = build_public_link(f"/auth/verify-email?token={raw_token}")
    send_email(
        to_email=email,
        subject="Verify your email",
        body=f"Verify your email by visiting: {verify_link}",
    )
    return DetailResponse(detail="If the account exists, a verification email was sent.")


@router.post("/verify-email", response_model=DetailResponse)
async def verify_email(payload: VerifyEmailRequest) -> DetailResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    token_hash = hash_action_token(payload.token)
    token_row = await db.consume_email_verify_token(token_hash)
    if not token_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token")
    expires_at = token_row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token expired")
    await db.mark_auth_user_email_verified(user_id=str(token_row["user_id"]))
    return DetailResponse(detail="Email verified")


@router.post("/request-password-reset", response_model=DetailResponse)
async def request_password_reset(payload: EmailRequest) -> DetailResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    email = payload.email.strip().lower()
    user = await db.get_auth_user_by_email(email)
    if not user:
        return DetailResponse(detail="If the account exists, a reset email was sent.")

    raw_token = generate_action_token()
    token_hash = hash_action_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=get_auth_settings().password_reset_ttl_hours)
    await db.create_password_reset_token(
        user_id=str(user["id"]),
        token_hash=token_hash,
        expires_at=expires_at,
    )
    reset_link = build_public_link(f"/auth/reset-password?token={raw_token}")
    send_email(
        to_email=email,
        subject="Reset your password",
        body=f"Reset your password by visiting: {reset_link}",
    )
    return DetailResponse(detail="If the account exists, a reset email was sent.")


@router.post("/reset-password", response_model=DetailResponse)
async def reset_password(payload: ResetPasswordRequest) -> DetailResponse:
    _ensure_auth_enabled()
    _ensure_db_ready()
    token_hash = hash_action_token(payload.token)
    token_row = await db.consume_password_reset_token(token_hash)
    if not token_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")
    expires_at = token_row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token expired")
    password_hash = hash_password(payload.password)
    await db.update_auth_user_password(user_id=str(token_row["user_id"]), password_hash=password_hash)
    return DetailResponse(detail="Password updated")
