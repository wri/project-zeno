"""Per-turn Langfuse trace attributes for /api/chat (pure, no IO)."""

from unittest.mock import MagicMock

import pytest

from src.api.services import chat_trace
from src.api.services.chat_trace import NudgeMatch, match_pending_nudge

DATASET_NUDGE = {
    "type": "dataset_choice",
    "options": ["Tree cover loss", "Tree cover gain"],
    "data": [{"dataset_id": 4}, {"dataset_id": 5}],
}


def test_exact_option_matches_with_type_and_index():
    assert match_pending_nudge(DATASET_NUDGE, "Tree cover gain") == (
        NudgeMatch(matched=True, type="dataset_choice", option_index=1)
    )


def test_surrounding_whitespace_is_ignored():
    match = match_pending_nudge(DATASET_NUDGE, "  Tree cover loss\n")
    assert match.matched and match.option_index == 0


def test_different_case_is_not_a_match():
    # A typed "yes" against a "Yes" option must stay typing, not a click.
    nudge = {"type": "confirm", "options": ["Yes", "No"]}
    assert not match_pending_nudge(nudge, "yes").matched


def test_text_that_merely_contains_an_option_is_not_a_match():
    assert not match_pending_nudge(
        DATASET_NUDGE, "Tree cover loss 2020"
    ).matched


def test_non_english_option_matches_exactly():
    nudge = {
        "type": "aoi_choice",
        "options": ["Córdoba, Argentina", "Córdoba, España"],
    }
    match = match_pending_nudge(nudge, "Córdoba, España")
    assert match == NudgeMatch(True, "aoi_choice", 1)


def test_duplicate_options_match_the_first():
    nudge = {"type": "confirm", "options": ["Yes", "Yes"]}
    assert match_pending_nudge(nudge, "Yes").option_index == 0


@pytest.mark.parametrize(
    "nudge",
    [
        None,
        {},
        {"type": "", "options": []},  # pick_dataset's cleared nudge
        {"type": "confirm", "options": []},
    ],
)
def test_no_pending_nudge_is_not_a_match(nudge):
    assert match_pending_nudge(nudge, "Tree cover loss") == chat_trace.NO_MATCH


@pytest.mark.parametrize(
    "nudge",
    [
        "Tree cover loss",
        {"type": "dataset_choice", "options": "Tree cover loss"},
        {"type": 3, "options": ["Tree cover loss"]},
    ],
)
def test_malformed_nudge_is_logged_and_not_a_match(nudge, monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr(chat_trace, "logger", logger)
    assert not match_pending_nudge(nudge, "Tree cover loss").matched
    logger.warning.assert_called_once()
