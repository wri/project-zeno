"""Tests for the highlight-markup contract.

The app finds the figures in a text block by the highlight span the model
writes. Two things have to hold: the rule reaches every prompt that writes a
text block, and the markup comes out again wherever a text block is quoted
back into the conversation instead of rendered.
"""

from src.agent.skills.loader import get_skill_body
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.agent.text_highlights import (
    HIGHLIGHT_GUIDE,
    HIGHLIGHT_KINDS,
    HIGHLIGHT_RULE,
    strip_highlights,
)
from src.agent.tools.add_text_widget import SPEC as ADD_TEXT_SPEC
from src.agent.tools.edit_text_widget import SPEC as EDIT_TEXT_SPEC
from src.api.services.nrt_summary import _SYSTEM as NRT_SUMMARY_SYSTEM


def test_guide_names_every_kind():
    for kind in HIGHLIGHT_KINDS:
        assert f'data-highlight="{kind}"' in HIGHLIGHT_GUIDE


def test_guide_reaches_the_insight_wording_guide():
    """The insight narrative and the display reviser both read
    WORDING_GUIDE, so composing the guide into it covers them both."""
    assert HIGHLIGHT_GUIDE in WORDING_GUIDE
    # The wording rules it was appended to are still there.
    assert "**Avoid:**" in WORDING_GUIDE


def test_guide_reaches_the_nrt_section_summary_prompt():
    assert "{highlight_guide}" in NRT_SUMMARY_SYSTEM


def test_guide_reaches_the_dashboard_skill():
    body = get_skill_body("dashboard")
    assert body is not None
    assert "{{HIGHLIGHT_GUIDE}}" not in body
    assert HIGHLIGHT_GUIDE in body


def test_rule_reaches_both_text_widget_tools():
    assert HIGHLIGHT_RULE in ADD_TEXT_SPEC.prompt_fragment
    assert HIGHLIGHT_RULE in EDIT_TEXT_SPEC.prompt_fragment


def test_strip_keeps_what_the_spans_wrapped():
    text = (
        'Loss rose by <span data-highlight="increase">12%</span> to '
        '<span data-highlight="value">4,200 ha</span>.'
    )
    assert strip_highlights(text) == "Loss rose by 12% to 4,200 ha."


def test_strip_leaves_plain_text_alone():
    assert strip_highlights("No markup here.") == "No markup here."
    assert strip_highlights("") == ""


def test_strip_is_idempotent():
    once = strip_highlights('<span data-highlight="value">27%</span> of it')
    assert strip_highlights(once) == once == "27% of it"


def test_strip_tolerates_sloppy_markup():
    """The model writes this markup, so the stripper cannot assume the tag
    is exactly as the guide spells it — an unknown kind, single quotes,
    extra attributes and odd spacing all have to come out."""
    text = (
        "<span  data-highlight='trend' class=\"x\" >8 Mha</ span> and "
        '<SPAN DATA-HIGHLIGHT="value">3%</SPAN>'
    )
    assert strip_highlights(text) == "8 Mha and 3%"
