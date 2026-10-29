"""resolve_environment: the run's label and URL from --env and --api-base-url,
including the ephemeral deployments CI runs against."""

import pytest

from goldset import cli
from goldset.ledger import make_run_id
from goldset.runner.api import APITestRunner

EPHEMERAL_URL = "http://horizon-ephemeral-1.us-east-1.elb.amazonaws.com:10123"


@pytest.mark.parametrize("env", ["staging", "prod", "local"])
def test_env_alone_uses_its_fixed_url(env):
    assert cli.resolve_environment(env, None) == (env, cli.ENV_URLS[env])


@pytest.mark.parametrize(
    "url, label",
    [
        ("https://api.staging.globalnaturewatch.org", "staging"),
        ("http://localhost:8000", "local"),
        ("https://api.globalnaturewatch.org", "prod"),
    ],
)
def test_explicit_url_decides_the_label(url, label):
    assert cli.resolve_environment("staging", url) == (label, url)


def test_ephemeral_keeps_its_label_whatever_the_url():
    """Without the explicit env, an ALB address would be labelled prod."""
    assert cli.resolve_environment("ephemeral", EPHEMERAL_URL) == (
        "ephemeral",
        EPHEMERAL_URL,
    )


def test_ephemeral_needs_a_url():
    with pytest.raises(ValueError, match="--api-base-url"):
        cli.resolve_environment("ephemeral", None)


def test_ephemeral_run_id_suffix():
    assert make_run_id("2026-10-17T12:00:00Z", "ephemeral", None) == (
        "20261017T120000Z_ephemeral"
    )


def test_ephemeral_token_is_api_token(monkeypatch):
    monkeypatch.delenv("STAGING_API_TOKEN", raising=False)
    monkeypatch.setenv("API_TOKEN", "generic")
    assert cli.require_api_token("ephemeral") == "generic"


def test_no_app_link_for_an_ephemeral_deployment():
    assert APITestRunner._build_app_thread_url(EPHEMERAL_URL, "t1") is None


def test_app_link_for_staging():
    assert (
        APITestRunner._build_app_thread_url(
            "https://api.staging.globalnaturewatch.org", "t1"
        )
        == "https://staging.globalnaturewatch.org/app/threads/t1"
    )
