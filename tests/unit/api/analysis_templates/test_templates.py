"""Registry checks that every analysis template must pass."""

from datetime import date

import pytest

from src.agent.datasets.config import DATASETS
from src.agent.i18n import MESSAGES
from src.api.services.analysis_templates.registry import (
    TEMPLATES,
    get_template,
)
from src.api.services.charts import DETERMINISTIC_GENERATORS
from src.api.user_profile_configs.languages import LANGUAGES

_CATALOG = {d["dataset_id"]: d for d in DATASETS}


def _widgets(kind):
    return [
        pytest.param(template, widget, id=f"{template.name}-{kind}")
        for template in TEMPLATES
        for widget in template.widgets
        if widget.kind == kind
    ]


def test_template_names_are_unique():
    names = [template.name for template in TEMPLATES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
def test_default_args_are_valid(template):
    start, end = template.parse_args({}).period(date(2026, 9, 23))
    assert start <= end


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
def test_template_has_a_widget(template):
    assert template.widgets


@pytest.mark.parametrize("template, widget", _widgets("chart"))
def test_chart_widget_has_a_curated_generator(template, widget):
    assert widget.dataset_id in _CATALOG
    assert any(
        g.can_handle(widget.dataset_id) for g in DETERMINISTIC_GENERATORS
    )


@pytest.mark.parametrize("template, widget", _widgets("chart"))
def test_chart_widget_names_charts_by_their_title_keys(template, widget):
    for title in widget.charts or ():
        assert title.startswith("charts.") and title in MESSAGES, title


@pytest.mark.parametrize("template, widget", _widgets("layer"))
def test_layer_widget_dataset_has_a_tile_layer(template, widget):
    record = _CATALOG[widget.dataset_id]
    assert record.get("tile_url") or record.get("layers")


@pytest.mark.parametrize("template, widget", _widgets("layer"))
def test_layer_widget_context_layer_is_in_the_catalog(template, widget):
    if widget.context_layer is None:
        return
    layers = _CATALOG[widget.dataset_id].get("context_layers") or []
    assert widget.context_layer in [layer["value"] for layer in layers]


@pytest.mark.parametrize("template, widget", _widgets("alerts"))
def test_alerts_widget_dataset_has_a_tile_layer(template, widget):
    assert _CATALOG[widget.dataset_id].get("tile_url")


@pytest.mark.parametrize("template, widget", _widgets("text"))
def test_text_widget_note_is_in_each_language_without_placeholders(
    template, widget
):
    notes = MESSAGES.get(widget.text_key, {})
    assert set(LANGUAGES) <= set(notes), widget.text_key
    for note in notes.values():
        # The builder formats the note with no values.
        assert note.format().strip()


def test_nrt_monitoring_covers_the_30_days_to_today():
    template = get_template("nrt-monitoring")
    today = date(2026, 10, 16)

    assert template.parse_args({}).period(today) == (
        date(2026, 9, 16),
        today,
    )
    assert [widget.kind for widget in template.widgets] == [
        "chart",
        "alerts",
        "imagery",
    ]


def test_post_2020_forest_loss_starts_at_the_natural_forest_baseline():
    template = get_template("post-2020-forest-loss")
    today = date(2026, 10, 7)

    assert template.parse_args({}).period(today) == (date(2021, 1, 1), today)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_i18n_keys_exist_in_each_supported_language(template, language):
    for key in (
        template.label_key,
        template.fallback_title_key,
        template.fallback_description_key,
    ):
        assert language in MESSAGES.get(key, {}), (key, language)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.name)
def test_fallback_text_takes_only_the_known_placeholders(template):
    values = {"aoi_name": "A", "start_date": "S", "end_date": "E"}
    for key in (
        template.fallback_title_key,
        template.fallback_description_key,
    ):
        for text in MESSAGES[key].values():
            text.format(**values)
