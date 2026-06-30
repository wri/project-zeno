"""Tests for the search_insights agent tool."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.tools.search_insights import (
    _score,
    _terms,
    search_insights,
)


def _content(command):
    return command.update["messages"][0].content


def _fake_insight(**kwargs):
    """Object shaped like InsightOrm (+ chart rows)."""
    defaults = dict(
        id=uuid4(),
        user_id="user-1",
        is_public=False,
        insight_text="Tree cover loss in the Amazon rose 12% over the period.",
        follow_up_suggestions=["Compare to fires"],
        created_at=datetime(2026, 6, 1),
        charts=[
            SimpleNamespace(
                position=0,
                title="Annual tree cover loss",
                chart_type="bar",
                x_axis="year",
                y_axis="loss_ha",
                color_field="",
                stack_field="",
                group_field="",
                series_fields=[],
                chart_data=[{"year": 2020, "loss_ha": 5}],
            )
        ],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_terms_drops_short_tokens_and_lowercases():
    assert _terms("Tree cover IN the Amazon") == [
        "tree",
        "cover",
        "the",
        "amazon",
    ]


def test_score_rewards_phrase_match():
    row = _fake_insight()
    terms = _terms("amazon tree cover")
    phrase_hit = _score(row, terms, "tree cover loss in the amazon")
    scattered = _score(row, terms, "amazon tree cover")
    assert phrase_hit > scattered > 0


@pytest.mark.asyncio
async def test_search_insights_surfaces_best_match():
    insight = _fake_insight()
    with patch(
        "src.agent.tools.search_insights._search_insights",
        new=AsyncMock(return_value=[insight]),
    ):
        command = await search_insights.coroutine(
            query="tree cover in the amazon", tool_call_id="t1"
        )

    # Surfaced into state exactly like the generator would.
    assert command.update["insight_id"] == str(insight.id)
    assert "Tree cover loss" in command.update["insight"]
    assert (
        command.update["charts_data"][0]["title"] == "Annual tree cover loss"
    )
    assert command.update["charts_data"][0]["type"] == "bar"
    message = command.update["messages"][0]
    assert message.status == "success"
    # Frontend treats it as an update (re-fetch/replace by id), not a new card.
    assert message.response_metadata["msg_type"] == "insight_updated"
    assert message.response_metadata["insight_id"] == str(insight.id)
    assert "Found a past insight" in message.content


@pytest.mark.asyncio
async def test_search_insights_picks_highest_scoring():
    weak = _fake_insight(
        insight_text="Fire alerts spiked in Indonesia.",
        created_at=datetime(2026, 6, 10),  # newer, but weaker match
        charts=[],
    )
    strong = _fake_insight(
        insight_text="Tree cover loss in the Amazon rose sharply.",
        created_at=datetime(2026, 6, 1),
    )
    with patch(
        "src.agent.tools.search_insights._search_insights",
        new=AsyncMock(return_value=[weak, strong]),
    ):
        command = await search_insights.coroutine(
            query="tree cover amazon", tool_call_id="t1"
        )
    assert command.update["insight_id"] == str(strong.id)


@pytest.mark.asyncio
async def test_search_insights_no_match():
    with patch(
        "src.agent.tools.search_insights._search_insights",
        new=AsyncMock(return_value=[]),
    ):
        command = await search_insights.coroutine(
            query="penguins in antarctica", tool_call_id="t1"
        )
    assert "No past insight matched" in _content(command)
    assert "insight_id" not in command.update
