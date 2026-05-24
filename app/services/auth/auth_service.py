"""
Authentication service: JWT generation/validation, password hashing, RBAC.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
# Monkeypatch bcrypt to fix passlib compatibility on newer python/bcrypt versions
if not hasattr(bcrypt, "__about__"):
    class About:
        __version__ = bcrypt.__version__
    bcrypt.__about__ = About()

from passlib.handlers.bcrypt import _BcryptCommon
original_finalize = _BcryptCommon._finalize_backend_mixin

@classmethod
def patched_finalize(mixin_cls, backend, dryrun):
    try:
        return original_finalize.__func__(mixin_cls, backend, dryrun)
    except ValueError as e:
        if "password cannot be longer than 72 bytes" in str(e):
            # Bypass the wrap bug check crash on newer bcrypt versions
            mixin_cls._has_2a_wraparound_bug = False
            return True
        raise

_BcryptCommon._finalize_backend_mixin = patched_finalize

from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.db.session import get_db
from app.models.models import User
from app.repositories.user_repository import UserRepository

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer(auto_error=False)


# ── Password utilities ────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── Token generation ──────────────────────────────────────────────────────────


def create_access_token(user_id: str, role: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_expire_minutes * 60


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """Returns (token, expiry_datetime)."""
    expiry = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": "refresh",
        "exp": expiry,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expiry


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc


# ── FastAPI dependencies ──────────────────────────────────────────────────────


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise AuthenticationError("Authorization header missing")

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise AuthenticationError("Not an access token")

    user_id: str = payload.get("sub", "")
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)

    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    return user


def require_roles(*roles: str):
    """Dependency factory: require that the current user has one of the given roles."""

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise AuthorizationError(
                f"Role '{current_user.role}' is not allowed. Required: {roles}"
            )
        return current_user

    return _check


require_admin = require_roles("admin")
require_analyst_or_admin = require_roles("admin", "analyst")
