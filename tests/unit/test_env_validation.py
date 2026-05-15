"""Tests for startup environment validation."""

import pytest


def test_check_env_passes_with_required_vars(monkeypatch):
    monkeypatch.setenv("DISCOGS_KEY", "key")
    monkeypatch.setenv("LASTFM_API_KEY", "key")
    monkeypatch.setenv("LASTFM_API_SECRET", "secret")

    import importlib

    import gateway.main as gm
    importlib.reload(gm)
    gm._check_env()  # should not raise


def test_check_env_raises_when_var_missing(monkeypatch):
    monkeypatch.delenv("DISCOGS_KEY", raising=False)
    monkeypatch.setenv("LASTFM_API_KEY", "key")
    monkeypatch.setenv("LASTFM_API_SECRET", "secret")

    import importlib

    import gateway.main as gm
    importlib.reload(gm)

    with pytest.raises(RuntimeError, match="DISCOGS_KEY"):
        gm._check_env()
