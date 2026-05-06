from src.agent.harness.artifact import Artifact


class InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, tuple[list[dict], dict]] = {}
        self._artifacts: dict[str, Artifact] = {}

    async def cache_data(
        self, stat_id: str, rows: list[dict], meta: dict
    ) -> None:
        self._data[stat_id] = (rows, meta)

    async def get_data(self, stat_id: str) -> tuple[list[dict], dict]:
        if stat_id not in self._data:
            raise KeyError(f"stat_id not found: {stat_id}")
        return self._data[stat_id]

    async def save_artifact(self, artifact: Artifact) -> None:
        self._artifacts[artifact.id] = artifact

    async def get_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    async def list_artifacts(self) -> list[Artifact]:
        return list(self._artifacts.values())
