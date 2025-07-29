from pydantic import BaseSettings, field_validator


class APISettings(BaseSettings):
    domains_allowlist: list[str] = []
    database_url: str

    daily_quoata_warning_threshold: int = 5
    admin_user_daily_quota: int = 100
    regular_user_daily_quota: int = 25
    anonymous_user_daily_quota: int = 10
    enable_quota_checking: bool = True

    @field_validator("domains_allowlist", mode="before")
    def validate_domains_allowlist(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v
