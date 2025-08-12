from pydantic import Field
from pydantic_settings import BaseSettings

from src.utils.env_loader import load_environment_variables

# Load environment variables first
load_environment_variables()


class _APISettings(BaseSettings):
    domains_allowlist_str: str = Field(default="", alias="DOMAINS_ALLOWLIST")
    database_url: str

    daily_quota_warning_threshold: int = 5
    admin_user_daily_quota: int = 100
    regular_user_daily_quota: int = 25
    anonymous_user_daily_quota: int = 10
    enable_quota_checking: bool = True

    @property
    def domains_allowlist(self) -> list[str]:
        if not self.domains_allowlist_str.strip():
            return []
        return [
            domain.strip() for domain in self.domains_allowlist_str.split(",")
        ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
APISettings = _APISettings()
