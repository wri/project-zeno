"""require_api_token: env-specific variables win, API_TOKEN is the fallback."""

from goldset import cli


def _clear(monkeypatch):
    for var in ("API_TOKEN", "STAGING_API_TOKEN", "PROD_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_env_specific_token_preferred(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("API_TOKEN", "generic")
    monkeypatch.setenv("STAGING_API_TOKEN", "staging-tok")
    assert cli.require_api_token("staging") == "staging-tok"


def test_falls_back_to_api_token(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("API_TOKEN", "generic")
    assert cli.require_api_token("prod") == "generic"


def test_local_has_no_env_specific_var(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("API_TOKEN", "generic")
    assert cli.require_api_token("local") == "generic"


def test_missing_everywhere_returns_none(monkeypatch, capsys):
    _clear(monkeypatch)
    assert cli.require_api_token("prod") is None
    out = capsys.readouterr().out
    assert "PROD_API_TOKEN or API_TOKEN is not set" in out


def test_missing_for_local_names_only_api_token(monkeypatch, capsys):
    _clear(monkeypatch)
    assert cli.require_api_token("local") is None
    out = capsys.readouterr().out
    assert "API_TOKEN is not set" in out
    assert "or API_TOKEN" not in out
