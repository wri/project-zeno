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

    `last_widget_ids` and `last_section_ids` are the ids of the widgets and
    the sections of the last dashboard edit, so that "remove that" has a
    target. The frontend sets them after it runs the steps.
    """

    dataset_id: Optional[int] = None
    area: Optional[ZapArea] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    context_layer: Optional[str] = None
    canopy_cover: Optional[int] = None
    page: Optional[Literal["map", "dashboard"]] = None
    dashboard_id: Optional[str] = None
    last_widget_ids: Optional[list[str]] = None
    last_section_ids: Optional[list[str]] = None


class ZapRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    current: ZapCurrent = Field(default_factory=ZapCurrent)
    # On a dashboard: the options that the user selected, as
    # {decision key: option value}, e.g. {"target": "widget:<id>"}. The
    # planner uses them in place of the jev answers. The frontend sends the
    # same prompt again with the option of a chip.
    choose: Optional[dict[str, str]] = None


class ZapDecisionOption(BaseModel):
    """An other option of a jev decision. The frontend sends `label` as a
    new request on the current state when the user selects it."""

    label: str
    probability: float
    # The option id, for `ZapRequest.choose`. Set for the decisions of a
    # dashboard edit, e.g. "widget:<id>", "section:<id>" or "dashboard".
    value: Optional[str] = None


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

    `source` is "user" for an option of `ZapRequest.choose`.
    """

    question: str
    label: str
    probability: float
    source: Optional[Literal["jev", "clairic", "code", "user"]] = None
    options: Optional[list[ZapDecisionOption]] = None
    clear: Optional[bool] = None
    # The decision key for `ZapRequest.choose` ("target", "destination",
    # "size", "widgets", "action"), and the id of the selected option.
    key: Optional[str] = None
    value: Optional[str] = None


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


class ZapPlacedWidgetBody(ZapWidgetBody):
    """`ZapWidgetBody` with the place of the widget: its position in its
    container and its section (None: the top level)."""

    position: Optional[int] = None
    section_id: Optional[str] = None


class ZapAddSectionArgs(BaseModel):
    """`add_section`: send `section` to
    `POST /api/dashboards/{dashboard_id}/sections`."""

    dashboard_id: str
    section: dict[str, Any]


class ZapMoveArgs(BaseModel):
    """`move`: send `patch` to
    `PATCH /api/dashboards/{dashboard_id}/widgets/{widget_id}`. `patch`
    always holds `section_id`; null moves the widget to the top level and
    must stay in the body."""

    dashboard_id: str
    widget_id: str
    widget_label: str
    destination_label: str
    patch: dict[str, Any]


class ZapResizeArgs(BaseModel):
    """`resize`: send `patch` to
    `PATCH /api/dashboards/{dashboard_id}/widgets/{widget_id}`. The
    endpoint replaces the config, so `patch.config` is the full config of
    the widget with the new `size` ("single": half width, "double": full
    width)."""

    dashboard_id: str
    widget_id: str
    widget_label: str
    size: Literal["single", "double"]
    patch: dict[str, Any]


class ZapRenameArgs(BaseModel):
    """`rename`: for `target_type` "dashboard", send `patch` to
    `PATCH /api/dashboards/{dashboard_id}`; for "section", to
    `PATCH /api/dashboards/{dashboard_id}/sections/{section_id}`."""

    dashboard_id: str
    target_type: Literal["dashboard", "section"]
    section_id: Optional[str] = None
    old_title: str
    title: str
    patch: dict[str, Any]


class ZapChangePeriodArgs(BaseModel):
    """`change_period`: build the widget again for a new period. If
    `analyze` is set (a chart), send it to `POST /api/analyze`, wait for
    the job and set `widget.insight_id`. Send `widget` to
    `POST /api/dashboards/{dashboard_id}/widgets`: it holds the position
    and the section of the old widget. Then, if `replace` is true, send
    `DELETE /api/dashboards/{dashboard_id}/widgets/{widget_id}`."""

    dashboard_id: str
    widget_id: str
    widget_label: str
    dataset_name: str
    old_start_date: Optional[str] = None
    old_end_date: Optional[str] = None
    replace: bool = True
    analyze: Optional[ZapAnalyzeBody] = None
    widget: ZapPlacedWidgetBody


class ZapRemoveArgs(BaseModel):
    """`remove`: for `target_type` "widget", send
    `DELETE /api/dashboards/{dashboard_id}/widgets/{widget_id}`; for
    "section", send
    `DELETE /api/dashboards/{dashboard_id}/sections/{section_id}?delete_widgets={delete_widgets}`.
    `widget_labels` are the widgets of the section, for the preview."""

    dashboard_id: str
    target_type: Literal["widget", "section"]
    widget_id: Optional[str] = None
    section_id: Optional[str] = None
    label: str
    delete_widgets: bool = False
    widget_labels: list[str] = Field(default_factory=list)


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
    - `add_section`: `args` is a `ZapAddSectionArgs`.
    - `move`: `args` is a `ZapMoveArgs`.
    - `resize`: `args` is a `ZapResizeArgs`.
    - `rename`: `args` is a `ZapRenameArgs`.
    - `change_period`: `args` is a `ZapChangePeriodArgs`.
    - `remove`: `args` is a `ZapRemoveArgs`.
    """

    kind: Literal[
        "dataset",
        "area",
        "analysis",
        "add_chart",
        "add_map",
        "add_template",
        "add_imagery",
        "add_section",
        "move",
        "resize",
        "rename",
        "change_period",
        "remove",
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
    # confirmation"): 0 for a map change, 1 for a dashboard addition or
    # layout edit with clear decisions, 2 for a removal, a new period, an
    # edit of more than one widget, or a decision that is not clear. None
    # when the plan has no steps.
    tier: Optional[int] = None
    # True when the frontend must show the plan as a preview and apply it
    # only after the user confirms it.
    needs_confirmation: Optional[bool] = None
