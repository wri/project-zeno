"""Tests for the analysis-template registry.

The registry is the extension point: every template is reachable through
it, and two callers — the dashboard writer's seal and the agent's tool
prompt — read it without importing a template. These tests hold that
contract for every registered template, so a new one is covered by them the
day it is added.
"""

import pytest
from pydantic import BaseModel

from src.api.services.analysis_templates import registry
from src.api.services.analysis_templates.base import AnalysisTemplate


def test_every_entry_resolves_to_a_template():
    for name in registry.TEMPLATE_NAMES:
        template = registry.get_template(name)
        assert isinstance(template, AnalysisTemplate)
        assert template.entry.name == name
        assert issubclass(template.params_model, BaseModel)


def test_default_params_are_usable_without_arguments():
    """A caller that names no parameters must still get a valid build."""
    for name in registry.TEMPLATE_NAMES:
        template = registry.get_template(name)
        assert isinstance(template.params_model(), BaseModel)


def test_params_refuse_what_the_template_does_not_take():
    """`extra="forbid"`: an unknown parameter is an error, never ignored."""
    for name in registry.TEMPLATE_NAMES:
        template = registry.get_template(name)
        with pytest.raises(Exception):
            template.params_model(not_a_real_parameter=1)


def test_sealed_types_come_from_the_entries():
    assert registry.SEALED_SECTION_TYPES == {
        entry.name for entry in registry.ENTRIES if entry.sealed
    }
    assert registry.DEFAULT_SECTION_TYPE not in registry.SEALED_SECTION_TYPES


def test_unknown_template_names_itself_and_the_known_ones():
    with pytest.raises(registry.UnknownTemplateError) as error:
        registry.get_template("no-such-template")
    assert "no-such-template" in str(error.value)
    for name in registry.TEMPLATE_NAMES:
        assert name in str(error.value)


def test_entry_metadata_is_prompt_ready():
    """The tool prompt is built from these strings, so they must be there."""
    for entry in registry.ENTRIES:
        assert entry.name == entry.name.lower()
        assert " " not in entry.name
        assert entry.label and entry.when_to_use and entry.params_help
    for name in registry.TEMPLATE_NAMES:
        assert name in registry.describe_templates()


def test_the_registry_stays_import_light():
    """The seal list must not cost an analytics client or a model client.

    ``dashboard_writer`` imports this module on every dashboard write.
    """
    import subprocess
    import sys

    probe = (
        "import sys;"
        "import src.api.services.analysis_templates.registry as r;"
        "assert r.SEALED_SECTION_TYPES;"
        "loaded = set(sys.modules);"
        "assert not [m for m in loaded if 'analysis_templates.nrt' in m], "
        "'a template module was imported';"
        "assert 'langchain_core' not in loaded, 'a model client was imported'"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
