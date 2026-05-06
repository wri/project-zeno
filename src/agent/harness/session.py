import asyncio
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from src.agent.harness.backends.protocol import ZenoBackend
from src.agent.harness.protocol import (
    AoiResolvedEvent,
    ArtifactEvent,
    DataFetchedEvent,
    ErrorEvent,
    MessageEvent,
    StateDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
    UIContext,
    ZenoEvent,
)

_END_OF_STREAM = object()


class ZenoSession:
    def __init__(
        self,
        agent: CompiledStateGraph,
        backend: ZenoBackend,
        ui_context: UIContext | None = None,
    ) -> None:
        self.agent = agent
        self.backend = backend
        self.ui_context = ui_context or UIContext()
        self._events: asyncio.Queue = asyncio.Queue()
        self.state: dict = {
            "aoi_refs": [],
            "dataset_id": None,
            "data_refs": [],
            "artifact_ids": [],
        }

    def emit(self, event: ZenoEvent) -> None:
        self._events.put_nowait(event)
        if isinstance(event, AoiResolvedEvent):
            refs = list(event.aoi_refs)
            self.state["aoi_refs"] = refs
            self._events.put_nowait(StateDeltaEvent(update={"aoi_refs": refs}))
        elif isinstance(event, DataFetchedEvent):
            data_refs = list(self.state.get("data_refs") or [])
            data_refs.append(event.stat_id)
            self.state["data_refs"] = data_refs
            self._events.put_nowait(
                StateDeltaEvent(update={"data_refs": data_refs})
            )
        elif isinstance(event, ArtifactEvent):
            ids = list(self.state.get("artifact_ids") or [])
            ids.append(event.artifact.id)
            self.state["artifact_ids"] = ids
            self._events.put_nowait(
                StateDeltaEvent(update={"artifact_ids": ids})
            )

    def set_dataset(self, dataset_id: str) -> None:
        self.state["dataset_id"] = dataset_id
        self._events.put_nowait(
            StateDeltaEvent(update={"dataset_id": dataset_id})
        )

    async def stream(self, query: str) -> AsyncIterator[ZenoEvent]:
        config = {"configurable": {"session": self}}
        context = {"session": self}
        inputs = {"messages": [HumanMessage(content=query)]}

        agent_task = asyncio.create_task(
            self._run_agent(inputs, config, context)
        )

        while True:
            if agent_task.done() and self._events.empty():
                break
            try:
                event = await asyncio.wait_for(
                    self._events.get(), timeout=0.05
                )
            except asyncio.TimeoutError:
                continue
            if event is _END_OF_STREAM:
                continue
            yield event

        exc = agent_task.exception()
        if exc is not None:
            yield ErrorEvent(message=str(exc), recoverable=False)

    async def _run_agent(
        self, inputs: dict, config: dict, context: dict
    ) -> None:
        seen_tool_call_ids: set[str] = set()
        try:
            async for chunk in self.agent.astream(
                inputs,
                config=config,
                context=context,
                stream_mode="updates",
            ):
                for _node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    for msg in update.get("messages") or []:
                        self._emit_message(msg, seen_tool_call_ids)
        finally:
            self._events.put_nowait(_END_OF_STREAM)

    def _emit_message(self, msg, seen: set[str]) -> None:
        if isinstance(msg, AIMessage):
            text, thinking = _split_ai_content(msg.content)
            if thinking:
                self._events.put_nowait(ThinkingEvent(text=thinking))
            if text:
                self._events.put_nowait(
                    MessageEvent(role="assistant", content=text)
                )
            for tc in msg.tool_calls or []:
                tcid = tc.get("id") or ""
                if tcid and tcid in seen:
                    continue
                if tcid:
                    seen.add(tcid)
                self._events.put_nowait(
                    ToolCallEvent(
                        name=tc.get("name", "?"),
                        args=dict(tc.get("args") or {}),
                        call_id=tcid,
                    )
                )
        elif isinstance(msg, ToolMessage):
            self._events.put_nowait(
                ToolResultEvent(
                    name=msg.name or "?",
                    call_id=msg.tool_call_id or "",
                    result=msg.content,
                )
            )


def _split_ai_content(content) -> tuple[str, str]:
    if isinstance(content, str):
        return (content.strip(), "")
    if isinstance(content, list):
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                text_parts.append(str(block))
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text", "")))
            elif btype == "thinking":
                thinking_parts.append(str(block.get("thinking", "")))
        return ("\n".join(p for p in text_parts if p).strip(),
                "\n".join(p for p in thinking_parts if p).strip())
    return ("", "")
