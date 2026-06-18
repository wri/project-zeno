"""Code executors for generate_insights."""

from src.agent.config import AgentSettings

from .base import CodeExecutor, ExecutionResult
from .gemini_executor import GeminiCodeExecutor
from .local_executor import LocalCodeExecutor


def get_code_executor() -> CodeExecutor:
    """Return the executor selected by the CODE_EXECUTOR setting.

    "local" (default) → smolagents in-process Python interpreter.
    "gemini"          → Google native code-execution sandbox.
    """
    selection = AgentSettings.code_executor.strip().lower()
    if selection == "gemini":
        return GeminiCodeExecutor()
    if selection == "local":
        return LocalCodeExecutor()
    raise ValueError(
        f"Unknown CODE_EXECUTOR '{selection}'. Use 'local' or 'gemini'."
    )


__all__ = [
    "CodeExecutor",
    "ExecutionResult",
    "GeminiCodeExecutor",
    "LocalCodeExecutor",
    "get_code_executor",
]
