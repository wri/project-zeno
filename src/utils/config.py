from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from src.utils.env_loader import load_environment_variables

# Load environment variables first
load_environment_variables()


class _APISettings(BaseSettings):
    domains_allowlist_str: str = Field(default="", alias="DOMAINS_ALLOWLIST")
    database_url: str

    # Database connection pool settings
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=3600, alias="DB_POOL_RECYCLE")

    daily_quota_warning_threshold: int = 5
    admin_user_daily_quota: int = 100
    regular_user_daily_quota: int = 25
    machine_user_daily_quota: int = 99999
    anonymous_user_daily_quota: int = 10
    ip_address_daily_quota: int = 50
    enable_quota_checking: bool = True

    nextjs_api_key: str = Field(..., alias="NEXTJS_API_KEY")
    max_user_signups: int = Field(default=-1, alias="MAX_USER_SIGNUPS")
    allow_public_signups: bool = Field(
        default=False, alias="ALLOW_PUBLIC_SIGNUPS"
    )

    @property
    def domains_allowlist(self) -> list[str]:
        if not self.domains_allowlist_str.strip():
            return []
        return [
            domain.strip() for domain in self.domains_allowlist_str.split(",")
        ]

    @field_validator("nextjs_api_key")
    def validate_nextjs_api_key(cls, value):
        if not value or value.strip() == "":
            raise ValueError(
                "NEXTJS_API_KEY must be set to a non-empty string"
            )
        return value

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
APISettings = _APISettings()
