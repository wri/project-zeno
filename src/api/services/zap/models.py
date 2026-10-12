from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ZapArea(BaseModel):
    name: str
    source: str
    src_id: str
    subtype: Optional[str] = None
    bbox: Optional[list[float]] = None


class ZapCurrent(BaseModel):
    """What the map shows now, so jev can keep it."""

    dataset_id: Optional[int] = None
    area: Optional[ZapArea] = None


class ZapRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    current: ZapCurrent = Field(default_factory=ZapCurrent)


class ZapDecision(BaseModel):
    """One jev answer, for the plan panel."""

    question: str
    label: str
    probability: float


class ZapAnalysis(BaseModel):
    dataset_id: int
    dataset_name: str
    area: ZapArea
    start_date: str
    end_date: str
    context_layer: Optional[str] = None
    canopy_cover: Optional[int] = None


class ZapStep(BaseModel):
    """One step of the plan. The frontend runs the steps in order.

    - `dataset`: `args` is the `dataset` object that pick_dataset streams.
    - `area`: `args` is a `ZapArea`.
    - `analysis`: `args` is a `ZapAnalysis`; the frontend runs it through
      POST /api/analyze.
    """

    kind: Literal["dataset", "area", "analysis"]
    title: str
    detail: str = ""
    args: dict[str, Any]


class ZapPlan(BaseModel):
    steps: list[ZapStep]
    decisions: list[ZapDecision]
    notes: list[str] = Field(default_factory=list)
