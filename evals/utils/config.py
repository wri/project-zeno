"""
Configuration management for E2E testing framework.
"""

from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TestConfig(BaseSettings):
    """Configuration for E2E test execution."""

    model_config = SettingsConfigDict(
        env_prefix="",  # No prefix, use exact env var names
        case_sensitive=False,  # Case-insensitive env var matching
        extra="ignore",  # Ignore extra env vars
    )

    # Test mode configuration
    test_mode: str = Field(
        default="local",
        description="Test mode: 'local' or 'api'",
    )
    langfuse_dataset: Optional[str] = Field(
        default=None,
        description="Langfuse dataset name",
    )

    # API configuration
    api_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for API tests",
    )
    api_token: Optional[str] = Field(
        default=None,
        description="API token for authentication",
    )

    # CSV mode configuration
    sample_size: int = Field(
        default=1,
        description="Sample size: 1 means run single test (CI/CD friendly), -1 means run all rows",
    )
    test_file: str = Field(
        default="experiments/e2e_test_dataset.csv",
        description="Path to test dataset CSV file",
    )
    test_group_filter: Optional[str] = Field(
        default=None,
        description="Filter by test_group column",
    )
    status_filter: Optional[List[str]] = Field(
        default=None,
        description="Filter by status column (comma-separated string from env will be converted to list)",
    )
    output_filename: Optional[str] = Field(
        default=None,
        description="Custom filename (timestamp will be appended)",
    )

    # Parallel execution configuration
    num_workers: int = Field(
        default=1,
        description="Number of parallel workers for test execution",
    )
    random_seed: int = Field(
        default=0,
        description="Random seed for sampling (0 means no random sampling)",
    )
    offset: int = Field(
        default=0,
        description="Offset for getting subset. Ignored if random_seed is not 0",
    )

    @field_validator("status_filter", mode="before")
    @classmethod
    def parse_status_filter(cls, v) -> Optional[List[str]]:
        """Convert comma-separated string to list, or return None."""
        if v is None or v == "":
            return None
        if isinstance(v, str):
            # Split by comma and strip whitespace
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("test_mode")
    @classmethod
    def validate_test_mode(cls, v: str) -> str:
        """Validate test_mode is 'local' or 'api'."""
        if v not in ["local", "api"]:
            raise ValueError(
                f"Invalid test_mode: {v}. Must be 'local' or 'api'"
            )
        return v

    @field_validator("sample_size")
    @classmethod
    def validate_sample_size(cls, v: int) -> int:
        """Validate sample_size is >= -1."""
        if v < -1:
            raise ValueError(f"SAMPLE_SIZE must be >= -1, got {v}")
        return v

    @field_validator("num_workers")
    @classmethod
    def validate_num_workers(cls, v: int) -> int:
        """Validate num_workers is >= 1."""
        if v < 1:
            raise ValueError(f"NUM_WORKERS must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def validate_api_token(self) -> "TestConfig":
        """Validate API token is provided when test_mode is 'api'."""
        if self.test_mode == "api" and not self.api_token:
            raise ValueError(
                "API_TOKEN environment variable is required when TEST_MODE=api"
            )
        return self

    def is_langfuse_mode(self) -> bool:
        """Check if Langfuse dataset mode is enabled."""
        return self.langfuse_dataset is not None

    def is_csv_mode(self) -> bool:
        """Check if CSV mode is enabled."""
        return not self.is_langfuse_mode()


def get_test_config() -> TestConfig:
    """Get validated test configuration from environment."""
    return TestConfig()
