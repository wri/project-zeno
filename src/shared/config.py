from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

load_dotenv()


class _SharedSettings(BaseSettings):
    """Shared infrastructure settings used by both API and Agent."""

    database_url: str

    # Database connection pool settings
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=30, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=3600, alias="DB_POOL_RECYCLE")

    # External API endpoints. The eoapi cache is the canonical tile host:
    # eoapi.globalnaturewatch.org serves a certificate that does not cover
    # the hostname and the staging host's certificate is expired (both
    # verified 2026-07-03), so browsers refuse tiles from either.
    eoapi_base_url: str = Field(
        default="https://eoapi-cache.globalnaturewatch.org",
        alias="EOAPI_BASE_URL",
    )

    api_base_url: str = Field(default="", alias="API_BASE_URL")

    # Dataset embeddings database
    dataset_embeddings_db: str = Field(
        default="gnw-dataset-index-gemini-v10",
        alias="DATASET_EMBEDDINGS_DB",
    )
    dataset_embeddings_model: str = Field(
        default="models/gemini-embedding-001",
        alias="DATASET_EMBEDDINGS_MODEL",
    )
    dataset_embeddings_task_type: str = Field(
        default="RETRIEVAL_QUERY",
        alias="DATASET_EMBEDDINGS_TASK_TYPE",
    )

    # The decision model (src/shared/decisions.py). It picks the dataset in
    # pick_dataset and the area in pick_aoi's model-selection path. The
    # selection LLM is the fallback when a call fails or times out.
    # DECISION_PROVIDER selects the model: "gemini" (Gemini Decision 1, the
    # default) or "jev".
    decision_provider: Literal["jev", "gemini"] = Field(
        default="gemini", alias="DECISION_PROVIDER"
    )
    # jev (Typesafe) on OpenRouter's alpha decisions API. Warm calls take
    # 0.2-0.5 s.
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    decision_model: str = Field(
        default="typesafe/jev-1.13", alias="DECISION_MODEL"
    )
    decisions_url: str = Field(
        default="https://openrouter.ai/api/alpha/decisions",
        alias="DECISIONS_URL",
    )
    decisions_timeout_seconds: float = Field(
        default=5.0, alias="DECISIONS_TIMEOUT_SECONDS"
    )
    # Gemini Decision 1 on the Gemini API (v1beta). Warm calls take 0.3-0.5
    # s, but the first calls after an idle period took 5-14 s (2026-11-18),
    # so its timeout is longer.
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    gemini_decision_model: str = Field(
        default="gemini-decision-1", alias="GEMINI_DECISION_MODEL"
    )
    gemini_decisions_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/decisions",
        alias="GEMINI_DECISIONS_URL",
    )
    gemini_decisions_timeout_seconds: float = Field(
        default=15.0, alias="GEMINI_DECISIONS_TIMEOUT_SECONDS"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
SharedSettings = _SharedSettings()
