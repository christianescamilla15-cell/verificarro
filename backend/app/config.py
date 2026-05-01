from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_vision_model: str = Field(
        default="claude-sonnet-4-6", alias="CLAUDE_VISION_MODEL"
    )

    port: int = Field(default=3009, alias="PORT")
    env: str = Field(default="development", alias="ENV")
    cors_origins: str = Field(
        default="http://localhost:5173", alias="CORS_ORIGINS"
    )

    playwright_headless: bool = Field(default=True, alias="PLAYWRIGHT_HEADLESS")
    scrape_timeout_ms: int = Field(default=30000, alias="SCRAPE_TIMEOUT_MS")
    repuve_rate_limit_per_sec: float = Field(
        default=1.0, alias="REPUVE_RATE_LIMIT_PER_SEC"
    )

    # --- Database ---
    # Default: aiosqlite local file. En Render: postgresql+asyncpg://...
    database_url: str = Field(
        default="sqlite+aiosqlite:///./verificarro.db",
        alias="DATABASE_URL",
    )

    @property
    def database_url_async(self) -> str:
        """Normaliza la URL de DB al driver async correcto.

        Render entrega `DATABASE_URL=postgres://...` (legacy heroku-style).
        SQLAlchemy 2.0 + asyncpg necesita `postgresql+asyncpg://...`.
        Esta property hace la traducción transparente.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url.removeprefix("postgres://")
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
        return url

    @property
    def database_url_sync(self) -> str:
        """Versión sync para Alembic (que internamente usa async pero la
        URL en `alembic.ini` puede ser la string async sin tocar)."""
        return self.database_url_async

    # --- Mercado Pago ---
    mp_access_token: str = Field(default="", alias="MP_ACCESS_TOKEN")
    mp_public_key: str = Field(default="", alias="MP_PUBLIC_KEY")
    mp_webhook_secret: str = Field(default="", alias="MP_WEBHOOK_SECRET")
    # Frontend URLs para success/failure/pending redirects
    mp_success_url: str = Field(
        default="http://localhost:5173/checkout/success",
        alias="MP_SUCCESS_URL",
    )
    mp_failure_url: str = Field(
        default="http://localhost:5173/checkout/failure",
        alias="MP_FAILURE_URL",
    )
    mp_pending_url: str = Field(
        default="http://localhost:5173/checkout/pending",
        alias="MP_PENDING_URL",
    )

    # --- Pricing ---
    price_basic_mxn: float = Field(default=49.0, alias="PRICE_BASIC_MXN")
    price_premium_mxn: float = Field(default=99.0, alias="PRICE_PREMIUM_MXN")

    # --- Auth ---
    # Para JWT signing y HMAC del magic link. CAMBIAR en producción.
    jwt_secret: str = Field(
        default="dev-only-change-in-production-9f8a3b2c1d4e5f6a",
        alias="JWT_SECRET",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    magic_link_ttl_minutes: int = Field(
        default=15, alias="MAGIC_LINK_TTL_MINUTES"
    )
    session_ttl_days: int = Field(default=30, alias="SESSION_TTL_DAYS")
    # URL base donde el frontend recibe el verify del magic link
    magic_link_base_url: str = Field(
        default="http://localhost:5173/auth/verify",
        alias="MAGIC_LINK_BASE_URL",
    )

    # --- Email (SMTP) ---
    # En dev se imprime el link al stdout cuando smtp_host está vacío.
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from_email: str = Field(
        default="hola@verificarro.mx", alias="SMTP_FROM_EMAIL"
    )
    smtp_from_name: str = Field(default="Verificarro", alias="SMTP_FROM_NAME")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
