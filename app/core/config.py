"""
app/core/config.py
------------------
Application configuration loaded from environment variables via pydantic-settings.

All secrets and environment-specific values must be set in the .env file.
Never hard-code credentials here.

TODO: Add field validators for DATABASE_URL format.
TODO: Add environment-specific config profiles (dev / staging / prod).
"""

from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/skill_leveling_db"
    # Connections per API process = db_pool_size + db_max_overflow. Keep
    # (processes x that number) below PostgreSQL's max_connections, or put PgBouncer in front.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    # Fail fast instead of letting requests pile up when every connection is busy.
    db_pool_timeout_seconds: int = 10

    # ── Security: access tokens (JWT) ─────────────────────────────────────────
    secret_key: SecretStr = SecretStr("change-me")  # signs JWTs; must be set in .env
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 15

    # ── Security: refresh tokens (httpOnly cookie) ───────────────────────────
    refresh_token_expire_days: int = 1
    refresh_reuse_grace_seconds: int = 10
    refresh_cookie_name: str = "refresh_token"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # ── Security: login rules ─────────────────────────────────────────────────
    login_max_failed_attempts: int = 5
    login_lockout_minutes: int = 10
    allow_student_self_registration: bool = True
    # Argon2 needs about 64 MB of RAM per hash. This caps how many run at once in each
    # process, so a burst of logins waits in a queue instead of exhausting memory.
    password_hash_workers: int = 4

    # ── Encryption (secret codes) ─────────────────────────────────────────────
    code_encryption_key: str = "change-me-to-a-fernet-key"

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    # Accepts a JSON list or a comma-separated string (as in .env.example).
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                import json

                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("secret_key")
    @classmethod
    def secret_key_is_strong(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret.startswith("change-me") or len(secret) < 32:
            raise ValueError(
                "SECRET_KEY must be a random string of at least 32 characters. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return value

    @model_validator(mode="after")
    def browser_settings_are_consistent(self) -> "Settings":
        if "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS can't contain '*' when cookies are used; list the frontend URLs.")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SAMESITE=none only works together with COOKIE_SECURE=true.")
        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("Set COOKIE_SECURE=true in production (serve the API over HTTPS).")
        return self

    @property
    def refresh_cookie_path(self) -> str:
        # The browser only sends the refresh cookie to /api/v1/auth/..., not with every API call.
        return f"{self.api_v1_prefix}/auth"


settings = Settings()
