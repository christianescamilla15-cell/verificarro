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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
