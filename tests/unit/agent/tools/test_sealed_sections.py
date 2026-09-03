"""The agent-side half of the section seal.

The repository is what actually refuses a write to a sealed section; these
cover the layer above it, whose job is to keep the model from trying: a
sealed section is not offered as a place to put a widget, and it is marked
as read-only wherever sections are listed.
"""

from types import SimpleNamespace
from uuid import uuid4

from src.agent.tools.common import (
    format_sections,
    resolve_section,
    sealed_error_command,
)
from src.api.repositories.dashboard_writer import SealedSectionError


def _section(title: str, type: str = "default"):
    return SimpleNamespace(id=uuid4(), title=title, type=type)


def _dashboard(*sections):
    return SimpleNamespace(id=uuid4(), name="Paraná", sections=list(sections))


def test_ordinary_section_resolves_by_title():
    section = _section("Deforestation")
    dashboard = _dashboard(section)

    resolved, message = resolve_section(dashboard, "deforestation")

    assert resolved is section
    assert message is None


def test_sealed_section_is_refused_as_a_widget_target():
    sealed = _section("Recent disturbance", type="nrt-monitoring")
    dashboard = _dashboard(sealed)

    resolved, message = resolve_section(dashboard, "Recent disturbance")

    assert resolved is None
    assert "read-only" in message
    # The reply has to say what to do instead, or the model just retries.
    assert "another section" in message


def test_sealed_section_is_refused_by_id_too():
    sealed = _section("Recent disturbance", type="nrt-monitoring")
    dashboard = _dashboard(sealed)

    resolved, message = resolve_section(dashboard, str(sealed.id))

    assert resolved is None
    assert "read-only" in message


def test_listing_marks_sealed_sections():
    listing = format_sections(
        _dashboard(
            _section("Deforestation"),
            _section("Recent disturbance", type="nrt-monitoring"),
        )
    )

    assert "'Deforestation'" in listing
    assert listing.count("[read-only]") == 1
    assert "'Recent disturbance'" in listing.split("[read-only]")[0]


def test_sealed_reply_names_the_only_way_forward():
    command = sealed_error_command(
        SealedSectionError("sec-1", "nrt-monitoring"), "call-1"
    )

    (message,) = command.update["messages"]
    assert message.status == "error"
    assert "read-only" in message.content
    assert "deleted and rebuilt" in message.content
    # Layout is editable, so the reply must not claim otherwise.
    assert "resize" in message.content
