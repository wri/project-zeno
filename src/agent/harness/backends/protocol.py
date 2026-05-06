from typing import Protocol

from src.agent.harness.artifact import Artifact


class ZenoBackend(Protocol):
    async def cache_data(
        self, stat_id: str, rows: list[dict], meta: dict
    ) -> None: ...

    async def get_data(self, stat_id: str) -> tuple[list[dict], dict]: ...

    async def save_artifact(self, artifact: Artifact) -> None: ...

    async def get_artifact(self, artifact_id: str) -> Artifact | None: ...

    async def list_artifacts(self) -> list[Artifact]: ...
