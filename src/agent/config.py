from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class _AgentSettings(BaseSettings):
    """Agent-specific settings for model configuration."""

    # Model configuration
    model: str = Field(default="gemini", alias="MODEL")
    small_model: str = Field(default="gemini-flash", alias="SMALL_MODEL")
    coding_model: str = Field(default="gemini-2.5-pro", alias="CODING_MODEL")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
AgentSettings = _AgentSettings()
