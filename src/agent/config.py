from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class _AgentSettings(BaseSettings):
    """Agent-specific settings for model configuration."""

    # Model configuration
    model: str = Field(default="gemini", alias="MODEL")
    small_model: str = Field(default="gemma4", alias="SMALL_MODEL")
    # Code executor selection: "sandboxed" (locked-down subprocess), "local"
    # (smolagents in-process) or "gemini" (Google native sandbox).
    code_executor: str = Field(default="local", alias="CODE_EXECUTOR")
    # Sandbox (CODE_EXECUTOR=sandboxed) tuning:
    #  - seccomp: install the syscall filter (blocks network/exec/fork). Linux
    #    + pyseccomp only; harmlessly no-ops elsewhere.
    #  - strict: also block opening new files (no file reads) — strongest, but
    #    can break code paths that lazily import. Leave off unless inputs are
    #    fully untrusted.
    sandbox_seccomp: bool = Field(default=True, alias="SANDBOX_SECCOMP")
    sandbox_strict: bool = Field(default=False, alias="SANDBOX_STRICT")
    # CODING_MODEL meaning depends on CODE_EXECUTOR:
    #  - "local": a MODEL_REGISTRY key (e.g. "qwen3-coder")
    #  - "gemini": a raw google-genai model id (e.g. "gemini-3.1-pro-preview")
    coding_model: str = Field(default="qwen3-coder", alias="CODING_MODEL")
    coding_fallback_models: str = Field(
        default="gpt-oss",
        alias="CODING_FALLBACK_MODELS",
    )
    fallback_models: str = Field(
        default="gpt-oss,gemini-flash", alias="FALLBACK_MODELS"
    )
    # Retries handled by ModelRetryMiddleware, so default should be 0
    # this is only used in unit tests
    llm_max_retries: int = Field(default=0, alias="LLM_MAX_RETRIES")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Create a singleton instance
AgentSettings = _AgentSettings()
