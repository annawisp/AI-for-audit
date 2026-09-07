from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI for Audit"
    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    api_cors_origins: str = Field(default="http://localhost:5173")

    database_path: str = "data/audit.sqlite3"
    upload_dir: str = "uploads"
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_allowed_extensions: str = ".txt,.pdf,.docx,.xlsx,.csv"

    @field_validator("app_env")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        allowed = {"development", "test", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"APP_ENV must be one of {sorted(allowed)}")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def allowed_upload_extensions(self) -> set[str]:
        return {
            extension.strip().lower()
            for extension in self.upload_allowed_extensions.split(",")
            if extension.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
