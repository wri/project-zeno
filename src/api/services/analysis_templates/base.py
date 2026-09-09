"""What an analysis template is, and what every template shares.

A template implements two operations over a dashboard:

* ``build`` — write a new section for a set of parameters;
* ``refresh`` — rebuild an existing one of its own sections for different
  parameters, in place.

Both take the loaded dashboard rather than an id, so a template picks its
own area and runs its own "already built" check without the caller needing
a hook for either. Both return a ``TemplateResult`` whose ``summary`` the
template writes itself, so no caller has to know what the section contains.

Everything a caller must handle is a ``TemplateError``: its message is
written for the user, so a tool or a route needs one ``except`` clause and
no knowledge of any particular template.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from src.api.data_models import DashboardOrm, DashboardSectionOrm
from src.api.services.analysis_templates.registry import (
    SEALED_SECTION_TYPES,
    TemplateEntry,
)


class TemplateError(Exception):
    """A build or refresh that cannot go ahead, in words for the user.

    Every subclass keeps that promise: ``str(error)`` is shown as-is. A
    caller catches this one type.
    """


class DataUnavailableError(TemplateError):
    """The data the section is made of could not be pulled.

    Fatal for the build: a section without its data says nothing.
    """


class AlreadyBuiltError(TemplateError):
    """The dashboard already carries this section, for these parameters.

    Building again costs a data pull and a model call, and leaves the reader
    two identical sections.
    """

    def __init__(self, message: str, section_id: str):
        self.section_id = section_id
        super().__init__(message)


class TargetGoneError(TemplateError):
    """The dashboard or section being written to no longer exists.

    Its own type, not a bare ``ValueError``: a build calls out to an
    analytics API, a catalog, an imagery provider and a model, any of which
    raises ``ValueError`` for its own reasons.
    """


@dataclass
class SectionContent:
    """A section gathered but not yet written.

    Building and refreshing differ only in where this lands, so a template
    has one gather step and two short write paths. ``config`` is the
    template's own record of what it built from — the window, the
    parameters — which ``writer`` stores on the section row alongside the
    template's name.
    """

    title: str
    description: str
    #: ``{"widget_type": ..., "insight_id": ..., "config": ...}`` each, in
    #: render order.
    widgets: list[dict]
    #: Anything else the template wants on the section row, beside its name
    #: and the parameters ``writer`` records for it. Free-form: nothing in
    #: the generic layer reads it, only the template that wrote it.
    config: dict[str, Any] = field(default_factory=dict)
    #: One line for a tool message: what was built, in the template's own
    #: words. No ids — the caller adds those.
    summary: str = ""
    #: Why a widget is missing, in words a caller can show the user.
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TemplateResult:
    """What a build or a refresh wrote."""

    template: str
    section_id: str
    widget_ids: list[str]
    summary: str
    warnings: list[str] = field(default_factory=list)


#: A template's own parameter model: it accepts that type and no other.
ParamsT = TypeVar("ParamsT", bound=BaseModel)


@runtime_checkable
class AnalysisTemplate(Protocol[ParamsT]):
    """The interface ``registry.get_template`` returns.

    A template module exports one instance of this as ``TEMPLATE``. It is
    generic in its parameter model, so a template types its own ``build``
    and ``refresh`` against ``NrtParams`` (say) rather than against
    ``BaseModel``.
    """

    #: The template's own registry metadata.
    entry: TemplateEntry
    #: The template's parameters. Callers construct it from what they were
    #: given, so its field defaults are the template's defaults and its
    #: bounds are the only bounds. Forbid extra fields, so a parameter this
    #: template does not take is refused rather than ignored.
    params_model: type[ParamsT]

    async def build(
        self,
        dashboard: DashboardOrm,
        *,
        user_id: str,
        params: ParamsT,
        language: str,
    ) -> TemplateResult:
        """Write a new section on this dashboard."""
        ...

    async def refresh(
        self,
        section: DashboardSectionOrm,
        dashboard: DashboardOrm,
        *,
        user_id: str,
        params: ParamsT,
        language: str,
    ) -> TemplateResult:
        """Rebuild one of this template's own sections, in place.

        Called both to re-run a section unchanged, with today's data, and to
        rebuild it for different parameters. The template cannot tell the
        two apart, and does not need to.
        """
        ...

    def describe(self, section: DashboardSectionOrm) -> str:
        """What this section currently covers, in one phrase for a message.

        The template's own words, because only it knows what its parameters
        mean: a period for one, a threshold or a comparison for the next.
        Read from the section's stored ``config``, never from a widget.
        """
        ...


def aoi_ref(aoi) -> dict:
    """A dashboard AOI row as the reference a template's pull takes.

    One projection, so every template hands the same four fields to the
    same handlers.
    """
    return {
        "source": aoi.source,
        "src_id": aoi.src_id,
        "subtype": aoi.subtype,
        "name": aoi.name,
    }


def first_aoi(dashboard: DashboardOrm):
    """The area a template covers, or None.

    Today a section covers the dashboard's first area. Portfolios of areas
    are a dashboard-level question, not a per-template one, so this is the
    one place it will change.
    """
    return dashboard.aois[0] if dashboard.aois else None


def templated_sections(
    dashboard: DashboardOrm, name: Optional[str] = None
) -> list[DashboardSectionOrm]:
    """The template-built sections on a dashboard, in render order.

    ``name`` narrows to one template; without it, every sealed section.
    """
    wanted = {name} if name else SEALED_SECTION_TYPES
    return [
        section
        for section in dashboard.sections or []
        if section.type in wanted
    ]


def stored_params(
    template: "AnalysisTemplate[Any]", section: DashboardSectionOrm
) -> BaseModel:
    """The parameters a section was last built with.

    ``writer`` records them on the section row under ``params``, so
    re-running a section unchanged needs nothing from the caller and nothing
    template-specific here. A section written before a parameter existed
    falls back to that parameter's default.
    """
    config = dict(section.config or {})
    return template.params_model(**(config.get("params") or {}))
