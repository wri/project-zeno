from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class _APISettings(BaseSettings):
    """API-specific settings for quotas, authentication, and access control."""

    mapbox_api_token: str = ""

    # Zap mode: the jev decision model on OpenRouter's decisions API.
    openrouter_api_key: str = ""
    jev_model: str = "typesafe/jev-1.13"
    jev_url: str = "https://openrouter.ai/api/alpha/decisions"
    jev_timeout_seconds: float = 20.0
    # Zap mode: the Clairic extraction model on OpenRouter's extractions
    # API, for the place, the time and the canopy cover. Same key as jev.
    extract_model: str = "cloudflare/clairic"
    extract_url: str = "https://openrouter.ai/api/alpha/extractions"
    extract_timeout_seconds: float = 8.0

    # Quota settings
    admin_user_daily_quota: int = 100
    regular_user_daily_quota: int = 25
    pro_user_daily_quota: int = 50
    machine_user_daily_quota: int = 99999
    enable_quota_checking: bool = True

    custom_aoi_analytics_enabled: bool = False
    analytics_api_base_url: str = "https://analytics.globalnaturewatch.org"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
APISettings = _APISettings()
