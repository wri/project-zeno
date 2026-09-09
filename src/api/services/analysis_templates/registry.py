"""The list of analysis templates, as metadata only.

This module imports nothing from the rest of the application, and it must
stay that way. Two callers need to know that a template exists without
paying for what it does:

* ``dashboard_writer`` reads ``SEALED_SECTION_TYPES`` to refuse edits to a
  templated section. Importing a template there would drag the analytics
  client, the imagery provider and a model client into every dashboard
  write.
* the agent's tool prompt lists the templates at import time, and needs
  only their names and one line each.

``get_template`` imports the template's own module on first use and returns
its ``TEMPLATE`` object.

One entry per template. The ``name`` is also the value stored in
``dashboard_sections.type``, so there is one list of template names, not
two.
"""

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - import cycle broken for runtime
    from src.api.services.analysis_templates.base import AnalysisTemplate

#: The type of a section a user or the agent composed widget by widget.
DEFAULT_SECTION_TYPE = "default"

_PACKAGE = "src.api.services.analysis_templates"


class UnknownTemplateError(Exception):
    """No template goes by that name."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"unknown analysis template '{name}'; "
            f"known: {', '.join(TEMPLATE_NAMES)}"
        )


@dataclass(frozen=True)
class TemplateEntry:
    """What is known about a template without importing it.

    ``label``, ``when_to_use`` and ``params_help`` are written for a model
    to read: they go into the tool prompt that offers the templates. Keep
    them to one line each.
    """

    #: Stored in ``dashboard_sections.type``. Lower-case, hyphenated.
    name: str
    #: Short human name, for a tool message.
    label: str
    #: When to reach for this template, in one sentence.
    when_to_use: str
    #: The template's own parameters, in one sentence. Read by a model, so
    #: it must name each field, its default and its bounds.
    params_help: str
    #: Module under this package that exports ``TEMPLATE``.
    module: str
    #: What changing those parameters costs the reader, in one phrase. It
    #: goes into the confirmation the agent must get first.
    change_warning: str = "replaces what the section shows"
    #: Whether the section it writes is read-only afterwards. Templates that
    #: gather data for one period are; a template that only laid out
    #: existing widgets would not be.
    sealed: bool = True


ENTRIES: tuple[TemplateEntry, ...] = (
    TemplateEntry(
        name="nrt-monitoring",
        label="near-real-time monitoring",
        when_to_use=(
            "the user wants to monitor an area, or asks what has been "
            "disturbed there recently"
        ),
        params_help=(
            "days: length of the alert window counted back from today "
            "(default 14, max 365)"
        ),
        change_warning=(
            "changes every figure in the section, and the previous ones "
            "are deleted"
        ),
        module="nrt_monitoring",
    ),
)

ENTRIES_BY_NAME: dict[str, TemplateEntry] = {
    entry.name: entry for entry in ENTRIES
}

TEMPLATE_NAMES: tuple[str, ...] = tuple(entry.name for entry in ENTRIES)

#: Section types no caller may edit. Read by ``dashboard_writer``.
SEALED_SECTION_TYPES = frozenset(
    entry.name for entry in ENTRIES if entry.sealed
)


def get_entry(name: str) -> Optional[TemplateEntry]:
    """The metadata for a template name, or None."""
    return ENTRIES_BY_NAME.get(name)


def get_template(name: str) -> "AnalysisTemplate[Any]":
    """The template itself, importing its module on first use.

    Raises ``UnknownTemplateError`` for a name no entry claims — including
    the type of a section written before a template was removed.
    """
    entry = ENTRIES_BY_NAME.get(name)
    if entry is None:
        raise UnknownTemplateError(name)
    module = import_module(f"{_PACKAGE}.{entry.module}")
    template = module.TEMPLATE
    # The registry and the module each name the template. They must agree,
    # or a section would be written under a type nothing can refresh.
    assert template.entry.name == entry.name, (
        f"{entry.module}.TEMPLATE is '{template.entry.name}', "
        f"registered as '{entry.name}'"
    )
    return template


def describe_templates() -> str:
    """The templates as prompt lines, for the tool that offers them."""
    return "\n".join(
        f"  - `{entry.name}` — {entry.label}. Use when {entry.when_to_use}. "
        f"Parameters: {entry.params_help}."
        for entry in ENTRIES
    )
