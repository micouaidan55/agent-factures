"""Teste la robustesse de evals/run.py sans jamais appeler l'API réelle."""

import anthropic
import pytest

import evals.run as run_module


def test_main_exits_before_creating_a_client_when_api_key_is_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("sys.argv", ["run.py"])

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Anthropic ne doit jamais être instancié sans clé d'API.")

    monkeypatch.setattr(anthropic, "Anthropic", fail_if_called)

    with pytest.raises(SystemExit) as exc_info:
        run_module.main()

    assert exc_info.value.code == 1
