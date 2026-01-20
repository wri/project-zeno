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

    # External API endpoints
    eoapi_base_url: str = Field(
        default="https://eoapi.staging.globalnaturewatch.org",
        alias="EOAPI_BASE_URL",
    )

    # Dataset embeddings database
    dataset_embeddings_db: str = Field(
        default="gnw-dataset-index-gemini-v1",
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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
SharedSettings = _SharedSettings()
