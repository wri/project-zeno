from langchain_core.language_models import BaseChatModel

from src.agent.llms import MODEL_REGISTRY


class ModelRegistry:
    """Thin wrapper over the existing project-wide model registry. Phase 1
    only supports LangChain chat models for the orchestrator and any future
    code paths; DSPy support will land when subagents move off stubs."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {
            "orchestrator": "sonnet",
            "geo": "haiku",
            "analyst": "sonnet",
        }

    def for_langgraph(self, component: str) -> BaseChatModel:
        name = self._mapping.get(component, component).lower()
        if name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model alias for component {component!r}: {name}"
            )
        return MODEL_REGISTRY[name]
