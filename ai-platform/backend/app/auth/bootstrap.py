from __future__ import annotations

import logging

from .security import hash_password
from .settings import get_auth_settings
from .. import db

logger = logging.getLogger(__name__)


async def bootstrap_admin_user() -> None:
    settings = get_auth_settings()
    if not settings.bootstrap_admin_enabled:
        return
    if settings.mode == "api_key":
        logger.warning("BOOTSTRAP_ADMIN_ENABLED ignored because AUTH_MODE=api_key")
        return
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        raise RuntimeError(
            "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set when BOOTSTRAP_ADMIN_ENABLED=true"
        )
    if not db.is_enabled():
        raise RuntimeError("BOOTSTRAP_ADMIN_ENABLED requires DATABASE_URL to be set")

    email = settings.bootstrap_admin_email.strip().lower()
    existing = await db.get_auth_user_by_email(email)
    if existing:
        return
    password = settings.bootstrap_admin_password
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        message = (
            "BOOTSTRAP_ADMIN_PASSWORD is too long for bcrypt (>72 bytes). "
            "Use ASCII and keep it under 72 bytes."
        )
        logger.error(message)
        raise RuntimeError(message)
    password_hash = hash_password(password)
    await db.create_auth_user(email=email, password_hash=password_hash, role="admin")
    logger.info("Bootstrap admin user created for %s", email)
