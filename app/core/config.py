from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Every knob the app has. Values come from the environment or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App -----------------------------------------------------------------
    PROJECT_NAME: str = "DM Master API"
    API_V1_PREFIX: str = "/api/v1"

    # Not 8000: this stack runs alongside others locally. Used by
    # `python -m app.cli dev` so the port can't drift from the frontend's.
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8001
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = False

    # --- Database ------------------------------------------------------------
    # Neon: postgresql+asyncpg://user:pass@ep-xxx.region.aws.neon.tech/dbname
    DATABASE_URL: PostgresDsn

    # --- Security ------------------------------------------------------------
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    SECRET_KEY: str = Field(min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALGORITHM: str = "HS256"

    # --- Cookies -------------------------------------------------------------
    # The refresh token lives in an httpOnly cookie the frontend never reads
    REFRESH_COOKIE_NAME: str = "refresh_token"
    COOKIE_SECURE: bool = False  # must be True in production (HTTPS only)
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    COOKIE_DOMAIN: str | None = None

    # --- CORS ----------------------------------------------------------------
    FRONTEND_URL: str = "http://localhost:3000"

    # NoDecode stops pydantic-settings from trying to JSON-parse this, so the
    # .env can hold a plain comma-separated list instead of a JSON array.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def cors_origin_regex(self) -> str | None:
        """Locally the dev server's port moves around, so allow any localhost
        port. Never active outside ENVIRONMENT=local."""
        if self.ENVIRONMENT == "local":
            return r"http://(localhost|127\.0\.0\.1):\d+"
        return None

    # --- Google OAuth --------------------------------------------------------
    # Create at https://console.cloud.google.com/apis/credentials
    # Authorised redirect URI: {BACKEND_URL}/api/v1/auth/google/callback
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    BACKEND_URL: str = "http://localhost:8000"

    @property
    def google_enabled(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.BACKEND_URL}{self.API_V1_PREFIX}/auth/google/callback"

    # --- Uploads -------------------------------------------------------------
    # Local disk. Swap app/services/media.py for S3/R2 when you scale past one
    # machine — the rest of the app only ever sees the returned URL.
    UPLOAD_DIR: str = "uploads"
    UPLOAD_URL_PREFIX: str = "/uploads"
    MAX_AVATAR_BYTES: int = 5 * 1024 * 1024
    MAX_ENTITY_IMAGE_BYTES: int = 12 * 1024 * 1024
    MAX_ENTITY_IMAGE_DIMENSION: int = 1600

    @property
    def UPLOAD_DIR_PATH(self) -> Path:
        return Path(self.UPLOAD_DIR)

    # --- AI drafting ---------------------------------------------------------
    # Optional: with no key the feature is simply off, and the API says so
    # rather than failing at the point of use. One provider for both halves —
    # drafting a paragraph and drawing one picture are small jobs, so the
    # cheap models are the right size.
    OPENAI_API_KEY: str | None = None

    # A second, admin-scoped key, only for reading what the account was
    # actually billed. The project key above cannot: OpenAI refuses billing
    # endpoints to it. Optional — without it the purse simply shows our own
    # ledger, which is what it did before.
    OPENAI_ADMIN_KEY: str | None = None
    AI_TEXT_MODEL: str = "gpt-4o-mini"

    # The mini model bills its output at a fifth of the full one for the same
    # token counts, and the pictures came back better rather than worse — the
    # cheap tier costs 0.24¢ against 1.15¢, and its *medium* tier undercuts
    # what the full model charged for *low*. Compared on one prompt at both
    # tiers before switching. It is also cheaper per image than the open-weight
    # models hosted elsewhere, which is the reason not to add a second provider.
    IMAGE_MODEL: str = "gpt-image-1-mini"
    IMAGE_SIZE: str = "1024x1024"
    IMAGE_QUALITY: str = "low"

    # --- First user ----------------------------------------------------------
    # Seeded by `python -m app.cli seed` so you can sign in immediately
    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "changeme123"


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is read once per process."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
