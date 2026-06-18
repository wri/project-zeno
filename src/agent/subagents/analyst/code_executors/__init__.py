"""Code executors for generate_insights."""

from src.agent.config import AgentSettings

from .base import CodeExecutor, ExecutionResult
from .gemini_executor import GeminiCodeExecutor
from .local_executor import LocalCodeExecutor
from .subprocess_executor import SubprocessSandboxExecutor


def get_code_executor() -> CodeExecutor:
    """Return the executor selected by the CODE_EXECUTOR setting.

    "sandboxed" → locked-down subprocess (scrubbed env + rlimits + seccomp);
                  the only option safe for untrusted input, no Docker needed.
    "local"     → smolagents in-process interpreter (fast, dev/trusted only).
    "gemini"    → Google native code-execution sandbox.
    """
    selection = AgentSettings.code_executor.strip().lower()
    if selection == "sandboxed":
        return SubprocessSandboxExecutor()
    if selection == "gemini":
        return GeminiCodeExecutor()
    if selection == "local":
        return LocalCodeExecutor()
    raise ValueError(
        f"Unknown CODE_EXECUTOR '{selection}'. "
        "Use 'sandboxed', 'local', or 'gemini'."
    )


__all__ = [
    "CodeExecutor",
    "ExecutionResult",
    "GeminiCodeExecutor",
    "LocalCodeExecutor",
    "SubprocessSandboxExecutor",
    "get_code_executor",
]
