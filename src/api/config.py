from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class _APISettings(BaseSettings):
    """API-specific settings for quotas, authentication, and access control."""

    # Quota settings
    daily_quota_warning_threshold: int = 5
    admin_user_daily_quota: int = 100
    regular_user_daily_quota: int = 25
    pro_user_daily_quota: int = 50
    machine_user_daily_quota: int = 99999
    enable_quota_checking: bool = True

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
APISettings = _APISettings()
