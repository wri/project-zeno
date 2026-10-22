"""Deterministic guards: cheap checks for failures the other checks miss.

An answer can pass ``agent_answer`` with no data behind it, or with no chart at
all. These guards catch that:

- ``chart_produced``: a case with an expected answer must produce a chart.
- ``answered_without_data``: fails a substantive answer given with no data pull
  and no dataset selected.
- ``web_fallback``: fails an answer that links to outside sites, a sign it came
  from web knowledge rather than pulled data.
- ``pull_source_match``: the data pull must use the expected dataset.

The first three run only on cases that expect a data pull. Each guard scores 1.0
when clean, 0.0 when violated, and ``None`` when it does not apply.
``pull_source_match`` also scores ``None`` when the pull records no dataset id,
and says why in ``actual_pull_source``.
"""

from __future__ import annotations

import re
from typing import Any

from goldset.evaluators.answer_evaluator import extract_final_answer_text
from goldset.evaluators.utils import last_statistics, normalize_value

# Substantive prose (vs a bare refusal/greeting): anything this long that
# arrives with no data behind it is an answer the user will believe.
SUBSTANTIVE_ANSWER_CHARS = 80

# Links to our own sites are not web fallback: the product serves map tiles from
# tiles.globalforestwatch.org and links to Global Forest Watch dashboards for
# figures it has just pulled. wri.org is deliberately not listed: a wri.org
# citation usually means the agent answered from a WRI blog post instead of
# pulling data.
_OWN_DOMAINS = ("globalnaturewatch.org", "globalforestwatch.org")
_LINK_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _data_was_pulled(agent_state: dict[str, Any]) -> bool:
    statistics = last_statistics(agent_state)
    if not statistics:
        return False
    if str(statistics.get("source_url") or "") or str(statistics.get("id") or ""):
        return True
    data = statistics.get("data")
    return bool(data)


def _pull_dataset_reference(statistics: dict[str, Any]) -> str:
    """The pull's explicit dataset registry id, or ``""`` when the entry has none.

    Most statistics entries carry an integer ``dataset_id`` alongside
    ``source_url``, ``id``, ``data``, ``start_date`` and ``end_date``; a few do
    not (see results/campaigns/20260801-pr08.md). Presence is checked by key
    rather than truthiness, so an id of 0 still counts as present.
    """
    if "dataset_id" in statistics:
        return normalize_value(statistics.get("dataset_id"))
    return ""


def evaluate_guards(
    agent_state: dict[str, Any],
    expects_data_pull: bool,
    expected_answer: str,
    expected_dataset_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "chart_produced_score": None,
        "answered_without_data_score": None,
        "web_fallback_score": None,
        "pull_source_match_score": None,
        "actual_web_links": None,
        "actual_pull_source": None,
    }

    answer_text = extract_final_answer_text(agent_state.get("messages", []))
    charts = agent_state.get("charts_data") or []
    pulled = _data_was_pulled(agent_state)
    dataset = agent_state.get("dataset") or {}
    dataset_selected = bool(normalize_value(dataset.get("dataset_id")))

    # chart_produced: without it, a missing chart only leaves charts_answer
    # unscored. Gated on expects_data_pull like the other guards, so a case that
    # expects clarification is exempt even when it sets an answer.
    if expected_answer and expects_data_pull:
        result["chart_produced_score"] = 1.0 if charts else 0.0

    # answered_without_data: a violation is a substantive answer with no pull
    # and no dataset selection behind it.
    if expects_data_pull:
        answered = len(answer_text.strip()) >= SUBSTANTIVE_ANSWER_CHARS
        violated = answered and not pulled and not dataset_selected
        result["answered_without_data_score"] = 0.0 if violated else 1.0

    # web_fallback: outside links in an answer that should come from pulled data
    # suggest it came from web knowledge instead.
    if expects_data_pull and answer_text:
        links = [
            link
            for link in _LINK_RE.findall(answer_text)
            if not any(domain in link.lower() for domain in _OWN_DOMAINS)
        ]
        result["web_fallback_score"] = 0.0 if links else 1.0
        if links:
            result["actual_web_links"] = "; ".join(sorted(set(links))[:5])

    # pull_source_match: compare only the entry's explicit dataset_id.
    # source_url names datasets by slug (/v0/land_change/<slug>/analytics), not by
    # id, so matching a short id such as "11" against it would hit dates
    # ("2024-11-01") and miss every correct slug. When dataset_id is missing the
    # guard abstains and records the source_url and id it saw.
    if expected_dataset_id and pulled:
        statistics = last_statistics(agent_state) or {}
        reference = _pull_dataset_reference(statistics)
        if not reference:
            source_url = normalize_value(statistics.get("source_url")) or "none"
            pull_id = normalize_value(statistics.get("id")) or "none"
            result["actual_pull_source"] = (
                "statistics entry carries no dataset_id "
                f"(source_url={source_url}, id={pull_id}); guard abstained"
            )
        else:
            result["actual_pull_source"] = reference
            # Accept ;-separated alternatives (for example "8;10"), as
            # evaluate_dataset_selection does, so a case where either dataset is
            # defensible can pass.
            expected_alternatives = {
                normalize_value(alternative)
                for alternative in str(expected_dataset_id).split(";")
                if normalize_value(alternative)
            }
            result["pull_source_match_score"] = (
                1.0 if reference in expected_alternatives else 0.0
            )

    return result
