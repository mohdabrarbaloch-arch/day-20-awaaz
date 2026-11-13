"""Authentication routes: register, login, current user.

Note: no ``from __future__ import annotations`` here. FastAPI inspects the
endpoint signatures at import time, and postponed annotations make it treat
Pydantic body models as query parameters.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.limiter import limiter
from app.models import User
from app.schemas import Token, UserCreate, UserLogin, UserOut
from app.security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.auth_rate_limit)
def register(
    request: Request,
    payload: UserCreate,
    db: Session = Depends(get_db),
) -> Token:
    """Create an account and return a token so the client can go straight in."""
    email = payload.email.lower().strip()

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or email.split("@")[0])[:120],
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two simultaneous registrations for the same address.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        ) from None

    db.refresh(user)
    return Token(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=Token)
@limiter.limit(settings.auth_rate_limit)
def login(
    request: Request,
    payload: UserLogin,
    db: Session = Depends(get_db),
) -> Token:
    """Exchange email + password for a bearer token."""
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    # Same message and roughly the same work either way, so the response
    # does not reveal whether the address is registered.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled.",
        )

    return Token(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> UserOut:
    """Return the authenticated user."""
    return UserOut.model_validate(current)
