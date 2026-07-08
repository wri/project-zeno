from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
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
        default="gnw-dataset-index-gemini-v3",
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

    # Sentinel-2 mosaic storage. Built MosaicJSON files are written to this
    # S3 bucket and served by the GFW tiles service at
    # https://tiles.globalforestwatch.org.
    mosaic_s3_bucket: str = Field(default="", alias="MOSAIC_S3_BUCKET")
    mosaic_s3_prefix: str = Field(default="mosaics", alias="MOSAIC_S3_PREFIX")
    mosaic_s3_region: Optional[str] = Field(
        default=None, alias="MOSAIC_S3_REGION"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
SharedSettings = _SharedSettings()
