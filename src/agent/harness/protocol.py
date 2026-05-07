"""Lightweight data models for the Zeno harness.

Events are no longer used. Tools update state via Command returns.
Streaming to frontends uses LangGraph's native stream_writer.
"""

from typing import Any, TypedDict


class ChartContent(TypedDict):
    spec: dict
    data: list[dict]


class MapContent(TypedDict):
    layers: list[dict]
    viewport: dict


class InsightContent(TypedDict):
    text: str
    summary: str


class TableContent(TypedDict):
    columns: list[str]
    rows: list[list[Any]]
