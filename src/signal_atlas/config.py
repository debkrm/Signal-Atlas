import os
from pathlib import Path
from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central application settings loaded strictly from local environment or .env.
    Hardcoded password fallbacks are eliminated to enforce security across public repositories.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database Connection URL (Must be configured via .env or DATABASE_URL env var)
    database_url: Optional[str] = Field(default=None)

    # Discrete connection parameters for fallback construction
    postgres_user: Optional[str] = Field(default=None)
    postgres_password: Optional[str] = Field(default=None)
    postgres_host: str = Field(default="127.0.0.1")
    postgres_port: int = Field(default=5433)
    postgres_db: str = Field(default="signal_atlas")

    # Storage paths
    data_dir: Path = Path("data")
    raw_dir: Path = Path("data/raw")

    # Ingestion tuning
    nse_timeout_seconds: int = 20
    nse_request_delay_seconds: float = 1.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )

    @model_validator(mode="after")
    def validate_database_configuration(self) -> "Settings":
        """
        Validates that database credentials are provided securely via .env or environment.
        Refuses to run with hardcoded default credentials.
        """
        if not self.database_url:
            if not self.postgres_password or not self.postgres_user:
                # If neither full URL nor explicit credentials provided, check for TEST_DATABASE_URL during CI
                test_url = os.environ.get("TEST_DATABASE_URL")
                if test_url:
                    self.database_url = test_url
                    return self
                raise ValueError(
                    "DATABASE_URL or POSTGRES_PASSWORD must be configured in your local .env file. "
                    "Insecure default password fallbacks are disabled for repository security."
                )
            self.database_url = (
                f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
