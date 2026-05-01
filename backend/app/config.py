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

    # --- Captcha solver (2captcha.com) ---
    # Si está vacío, REPUVE cae al flow legacy "captcha_required" cuando
    # Google reCaptcha bloquea la consulta. Si está set, intentamos
    # resolver vía 2Captcha (~$0.003 USD por solve).
    captcha_solver_api_key: str = Field(
        default="", alias="CAPTCHA_SOLVER_API_KEY"
    )

    # Cantidad máxima de intentos por consulta REPUVE cuando el captcha
    # bypass es rechazado. 1 = single-shot, 2 = un retry. Más allá de 2
    # los retornos diminish y la UX sufre.
    repuve_retry_attempts: int = Field(
        default=2, alias="REPUVE_RETRY_ATTEMPTS"
    )

    # Proxy residencial MX para REPUVE — sube el éxito del captcha bypass
    # de ~30% a ~80% porque la IP del solver de 2Captcha y la nuestra
    # entran al mismo país y rango.
    #
    # Dos formatos soportados (mutuamente exclusivos):
    #
    #   1. URL embedida (legacy):
    #      PROXY_URL=http://user:pass@host:port
    #      ⚠ Si el password tiene caracteres especiales (+, /, @, :) hay
    #      que percent-encodearlos. Es frágil.
    #
    #   2. Campos separados (preferido):
    #      PROXY_SERVER=http://host:port
    #      PROXY_USERNAME=user
    #      PROXY_PASSWORD=pass (literal, sin encoding)
    #
    # Vacío por default (uso direct connection sin proxy).
    proxy_url: str = Field(default="", alias="PROXY_URL")
    proxy_server: str = Field(default="", alias="PROXY_SERVER")
    proxy_username: str = Field(default="", alias="PROXY_USERNAME")
    proxy_password: str = Field(default="", alias="PROXY_PASSWORD")

    # Directorio del browser profile persistente — guarda cookies,
    # localStorage, IndexedDB entre runs. Después de algunas consultas,
    # Google ve historia "humana" en el browser y sube el trust score.
    # Se incluye en .gitignore (artefacto local).
    playwright_profile_dir: str = Field(
        default="./.playwright-profile",
        alias="PLAYWRIGHT_PROFILE_DIR",
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
    # Tier "search" y "dealer" son passes mensuales (~30 días de uso) que
    # requieren validación operacional manual hasta que implementemos
    # subscriptions reales con MP preapproval. El frontend muestra los 4
    # tiers; el backend acepta payments y nos avisa por email para
    # activar el pase. Cuando volumen lo justifique, migrar a billing
    # automático con MP subscriptions.
    price_basic_mxn: float = Field(default=49.0, alias="PRICE_BASIC_MXN")
    price_premium_mxn: float = Field(default=99.0, alias="PRICE_PREMIUM_MXN")
    price_search_mxn: float = Field(default=199.0, alias="PRICE_SEARCH_MXN")
    price_dealer_mxn: float = Field(default=1499.0, alias="PRICE_DEALER_MXN")

    # --- WhatsApp tier Premium ---
    # Número del soporte oficial Verificarro (incluye código de país,
    # SIN +). El frontend genera links wa.me/{numero}?text=... para que
    # el usuario tier Premium chatee directo con Christian sin pasar
    # por formulario. Vacío en dev → botones se ocultan en frontend.
    whatsapp_support_number: str = Field(
        default="",
        alias="WHATSAPP_SUPPORT_NUMBER",
        description="Formato: 521XXXXXXXXXX (52 = MX, 1 = celular)",
    )

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
