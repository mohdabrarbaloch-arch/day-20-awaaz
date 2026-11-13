"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import JobStatus


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if v.isdigit() or v.isalpha():
            raise ValueError("password must mix letters and numbers")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------------------------------------------------------------------------
# Transcriptions
# --------------------------------------------------------------------------
class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


class TranscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_name: str
    content_type: str
    size_bytes: int
    status: JobStatus
    error: str | None = None
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float | None = None
    model_name: str | None = None
    processing_ms: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TranscriptionDetail(TranscriptionOut):
    segments: list[SegmentOut] = Field(default_factory=list)


class TranscriptionList(BaseModel):
    items: list[TranscriptionOut]
    total: int
    limit: int
    offset: int


class HealthOut(BaseModel):
    status: str
    engine_ready: bool
    model: str
    version: str
