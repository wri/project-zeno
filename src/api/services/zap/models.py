from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ZapArea(BaseModel):
    name: str
    source: str
    src_id: str
    subtype: Optional[str] = None
    bbox: Optional[list[float]] = None


class ZapCurrent(BaseModel):
    """What the map shows now. The planner starts from this state and
    changes only what the request names. All fields are optional: a client
    that sends only the dataset and the area gets the planner of phase 1
    for the other fields.

    `page` selects the planner: None or "map" for the map, "dashboard" for
    the dashboard `dashboard_id`.
    """

    dataset_id: Optional[int] = None
    area: Optional[ZapArea] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    context_layer: Optional[str] = None
    canopy_cover: Optional[int] = None
    page: Optional[Literal["map", "dashboard"]] = None
    dashboard_id: Optional[str] = None


class ZapRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    current: ZapCurrent = Field(default_factory=ZapCurrent)


class ZapDecisionOption(BaseModel):
    """An other option of a jev decision. The frontend sends `label` as a
    new request on the current state when the user selects it."""

    label: str
    probability: float


class ZapDecision(BaseModel):
    """One answer, for the plan panel.

    `source` tells which path gave the value: "jev" (an option of the
    decision model), "clairic" (a value of the extraction model) or "code"
    (a calendar rule on the time words of Clairic).

    `options` holds up to three other options of a jev decision, best
    first. The selected option is not in the list, and neither are the
    "keep" and "none" options. Absent for a Clairic or code value.

    `clear` tells if the decision is clear (see `tiers.py`). On a
    dashboard, a plan with a decision that is not clear needs a
    confirmation.
    """

    question: str
    label: str
    probability: float
    source: Optional[Literal["jev", "clairic", "code"]] = None
    options: Optional[list[ZapDecisionOption]] = None
    clear: Optional[bool] = None


class ZapAnalysis(BaseModel):
    dataset_id: int
    dataset_name: str
    area: ZapArea
    start_date: str
    end_date: str
    context_layer: Optional[str] = None
    canopy_cover: Optional[int] = None


# --- The args of the dashboard steps ----------------------------------------
# The contract is in docs/zap-mode-plan.md ("Dashboard step contract").


class ZapAoi(BaseModel):
    """An area as `POST /api/analyze` reads it (`AreaOfInterest`)."""

    source: str
    src_id: str
    subtype: str


class ZapAnalyzeBody(BaseModel):
    """The body of `POST /api/analyze` (`AnalyzeRequest`), with no
    `thread_id`."""

    aois: list[ZapAoi]
    dataset_id: int
    start_date: str
    end_date: str
    context_layer: Optional[str] = None
    canopy_cover: Optional[int] = None


class ZapWidgetBody(BaseModel):
    """The body of `POST /api/dashboards/{id}/widgets`
    (`DashboardWidgetCreateRequest`). For an insight widget, the frontend
    sets `insight_id` when the analysis job ends."""

    widget_type: Literal["insight", "map"]
    insight_id: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class ZapAddChartArgs(BaseModel):
    """`add_chart`: send `analyze` to `POST /api/analyze` and wait for the
    job. Then send `widget`, with the `insight_id` of the job, to
    `POST /api/dashboards/{dashboard_id}/widgets`."""

    dashboard_id: str
    dataset_name: str
    analyze: ZapAnalyzeBody
    widget: ZapWidgetBody


class ZapAddMapArgs(BaseModel):
    """`add_map`: send `widget` to
    `POST /api/dashboards/{dashboard_id}/widgets`. `widget.config.dataset`
    is the map layer snapshot of `widget_configs.dataset_config`."""

    dashboard_id: str
    dataset_name: str
    widget: ZapWidgetBody


class ZapAddTemplateArgs(BaseModel):
    """`add_template`: send `{"template": template, "args": args}` to
    `POST /api/dashboards/{dashboard_id}/sections/from-template`."""

    dashboard_id: str
    template: str
    args: dict[str, Any] = Field(default_factory=dict)


class ZapMosaicQuery(BaseModel):
    """The path values and the query of
    `POST /mosaic/create/{source}/{src_id}`."""

    source: str
    src_id: str
    target_date: str
    window_days: int
    max_cloud_cover: int
    max_items: int


class ZapAddImageryArgs(BaseModel):
    """`add_imagery`: build the mosaic with `mosaic`. Then add the
    statistics of the mosaic response to `widget.config.imagery`, and send
    `widget` to `POST /api/dashboards/{dashboard_id}/widgets`. The planner
    computes `mosaic_id`, `tile_url` and `tilejson_url` from the recipe, as
    the mosaic service does."""

    dashboard_id: str
    mosaic: ZapMosaicQuery
    widget: ZapWidgetBody


class ZapStep(BaseModel):
    """One step of the plan. The frontend runs the steps in order.

    Map page:

    - `dataset`: `args` is the `dataset` object that pick_dataset streams.
    - `area`: `args` is a `ZapArea`.
    - `analysis`: `args` is a `ZapAnalysis`; the frontend runs it through
      POST /api/analyze.

    Dashboard page:

    - `add_chart`: `args` is a `ZapAddChartArgs`.
    - `add_map`: `args` is a `ZapAddMapArgs`.
    - `add_template`: `args` is a `ZapAddTemplateArgs`.
    - `add_imagery`: `args` is a `ZapAddImageryArgs`.
    """

    kind: Literal[
        "dataset",
        "area",
        "analysis",
        "add_chart",
        "add_map",
        "add_template",
        "add_imagery",
    ]
    title: str
    detail: str = ""
    args: dict[str, Any]


class ZapPlan(BaseModel):
    steps: list[ZapStep]
    decisions: list[ZapDecision]
    notes: list[str] = Field(default_factory=list)
    # The state after the frontend runs the steps. The frontend sends it
    # back as `current` with the next request.
    state: Optional[ZapCurrent] = None
    # The tier of the plan (docs/zap-mode-plan.md, "Tiers and
    # confirmation"): 0 for a map change, 1 for a dashboard addition with
    # clear decisions, 2 for a dashboard addition with a decision that is
    # not clear. None when the plan has no steps.
    tier: Optional[int] = None
    # True when the frontend must show the plan as a preview and apply it
    # only after the user confirms it.
    needs_confirmation: Optional[bool] = None
