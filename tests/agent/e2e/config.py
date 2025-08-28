"""
Configuration management for E2E testing framework.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class TestConfig:
    """Configuration for E2E test execution."""

    # Test mode configuration
    test_mode: str = "local"  # "local" or "api"
    langfuse_dataset: Optional[str] = None

    # API configuration
    api_base_url: str = "http://localhost:8000"
    api_token: Optional[str] = None

    # CSV mode configuration
    sample_size: int = (
        1  # 1 means run single test (CI/CD friendly), -1 means run all rows
    )
    test_file: str = "experiments/e2e_test_dataset.csv"

    @classmethod
    def from_environment(cls) -> "TestConfig":
        """Create configuration from environment variables."""
        return cls(
            test_mode=os.getenv("TEST_MODE", "local"),
            langfuse_dataset=os.getenv("LANGFUSE_DATASET"),
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
            api_token=os.getenv("API_TOKEN"),
            sample_size=int(os.getenv("SAMPLE_SIZE", "1")),
            test_file=os.getenv(
                "TEST_FILE", "experiments/e2e_test_dataset.csv"
            ),
        )

    def validate(self) -> None:
        """Validate configuration settings."""
        if self.test_mode not in ["local", "api"]:
            raise ValueError(
                f"Invalid test_mode: {self.test_mode}. Must be 'local' or 'api'"
            )

        if self.test_mode == "api" and not self.api_token:
            raise ValueError(
                "API_TOKEN environment variable is required when TEST_MODE=api"
            )

        if self.sample_size < -1:
            raise ValueError(
                f"SAMPLE_SIZE must be >= -1, got {self.sample_size}"
            )

    def is_langfuse_mode(self) -> bool:
        """Check if Langfuse dataset mode is enabled."""
        return self.langfuse_dataset is not None

    def is_csv_mode(self) -> bool:
        """Check if CSV mode is enabled."""
        return not self.is_langfuse_mode()


def get_test_config() -> TestConfig:
    """Get validated test configuration from environment."""
    config = TestConfig.from_environment()
    config.validate()
    return config
