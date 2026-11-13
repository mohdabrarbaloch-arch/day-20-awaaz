"""Application settings, loaded from the environment.

Every value here has a safe development default so the app boots with zero
configuration, but nothing secret is ever hardcoded for production use.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables (or a local ``.env`` file).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "Awaaz"
    environment: str = "development"
    debug: bool = False

    # --- Security ----------------------------------------------------------
    # MUST be overridden in production. The app refuses to start in
    # production with this default (see ``validate_for_production``).
    secret_key: str = "dev-only-insecure-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    bcrypt_rounds: int = 12

    # --- Database ----------------------------------------------------------
    # SQLite by default; point at PostgreSQL in production.
    database_url: str = "sqlite:///./awaaz.db"

    # --- Speech engine -----------------------------------------------------
    # faster-whisper model size: tiny | base | small | medium | large-v3
    whisper_model: str = "tiny"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 5
    # Cap on how long a single job may run before we give up on it.
    transcription_timeout_seconds: int = 900

    # --- Uploads -----------------------------------------------------------
    max_upload_mb: int = 25
    upload_dir: str = "./uploads"
    allowed_audio_types: str = (
        "audio/wav,audio/x-wav,audio/mpeg,audio/mp3,audio/mp4,audio/m4a,"
        "audio/x-m4a,audio/ogg,audio/webm,audio/flac,audio/x-flac,"
        "video/mp4,video/webm"
    )

    # --- HTTP --------------------------------------------------------------
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    rate_limit: str = "30/minute"
    auth_rate_limit: str = "10/minute"

    # --- Derived helpers ---------------------------------------------------
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def allowed_types(self) -> set[str]:
        return {t.strip().lower() for t in self.allowed_audio_types.split(",") if t.strip()}

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def validate_for_production(self) -> None:
        """Fail loudly rather than run production with development defaults."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.secret_key.startswith("dev-only"):
            problems.append("SECRET_KEY is still the development default")
        if len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be at least 32 characters")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL should point at PostgreSQL in production")
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (one instance per process)."""
    return Settings()


settings = get_settings()
