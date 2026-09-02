from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class _AgentSettings(BaseSettings):
    """Agent-specific settings for model configuration."""

    # Model configuration
    model: str = Field(default="gemini", alias="MODEL")
    small_model: str = Field(default="gemini-flash", alias="SMALL_MODEL")
    coding_model: str = Field(
        default="gemini-3.1-pro-preview", alias="CODING_MODEL"
    )
    coding_fallback_models: str = Field(
        default="gemini-2.5-pro,gemini-3-flash-preview",
        alias="CODING_FALLBACK_MODELS",
    )
    fallback_models: str = Field(
        default="gemini-flash,gemini-flash-lite", alias="FALLBACK_MODELS"
    )
    # Retries handled by ModelRetryMiddleware, so default should be 0
    # this is only used in unit tests
    llm_max_retries: int = Field(default=0, alias="LLM_MAX_RETRIES")

    # Kill switch for the pick_aoi geocoder's table-aware normalisation
    # (PZB-1272). Set false to search only the place name the geocoder
    # extracted and to choose among candidates with the model again, which
    # is the behaviour that shipped before that change. Extraction still
    # returns the canonical name, alternatives and area type; the geocoder
    # simply ignores them.
    aoi_normalizer_enabled: bool = Field(
        default=True, alias="AOI_NORMALIZER_ENABLED"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
AgentSettings = _AgentSettings()
