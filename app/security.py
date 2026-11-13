"""Password hashing, JWT issuing/verification and the auth dependency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.bcrypt_rounds,
)

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    # bcrypt silently truncates past 72 bytes; reject rather than surprise.
    if len(password.encode("utf-8")) > 72:
        raise ValueError("password must be at most 72 bytes")
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time-ish verification via passlib."""
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(subject: str | int, expires_minutes: int | None = None) -> str:
    """Issue a signed JWT for the given subject (user id)."""
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": str(subject), "exp": expire, "iat": datetime.now(UTC)}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> str | None:
    """Return the subject from a valid token, or ``None``."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub is not None else None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to a live user, or raise 401."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized

    subject = decode_token(credentials.credentials)
    if subject is None:
        raise unauthorized

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise unauthorized from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user
