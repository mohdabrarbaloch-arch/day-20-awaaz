"""ORM models: users, transcriptions and their timed segments."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobStatus(str, enum.Enum):
    """Lifecycle of a transcription job."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transcriptions: Mapped[list[Transcription]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Transcription(Base):
    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # --- Source file -------------------------------------------------------
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Job state ---------------------------------------------------------
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=20),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Results -----------------------------------------------------------
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship(back_populates="transcriptions")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="transcription",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Segment.index",
    )

    __table_args__ = (Index("ix_transcriptions_user_created", "user_id", "created_at"),)


class Segment(Base):
    """One timed chunk of speech, as emitted by the ASR engine."""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcription_id: Mapped[int] = mapped_column(
        ForeignKey("transcriptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    avg_logprob: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_speech_prob: Mapped[float | None] = mapped_column(Float, nullable=True)

    transcription: Mapped[Transcription] = relationship(back_populates="segments")
