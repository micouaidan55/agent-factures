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


def test_main_stops_once_the_cost_budget_is_reached(monkeypatch, tmp_path, capsys):
    import json

    from agent_factures.agent.loop import AgentResult
    from agent_factures.extraction.models import Status, Verdict

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    documents = [
        {"file": f"{n}.pdf", "expected_status": "a_revoir", "expected_issues": [], "accept": False, "invoice": None}
        for n in range(3)
    ]
    (dataset / "expected.json").write_text(json.dumps({"today": "2026-09-24", "documents": documents}))

    processed = []

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def process(self, path):
            processed.append(path.name)
            return AgentResult(
                invoice=None, partial_extraction=None,
                verdict=Verdict(status=Status.NEEDS_REVIEW, explanation="Pas une facture."),
                issues=[], trace=[], input_tokens=0, output_tokens=0, cost_usd=1.0,
            )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(anthropic, "Anthropic", lambda: object())
    monkeypatch.setattr(run_module, "InvoiceAgent", FakeAgent)
    monkeypatch.setattr(
        "sys.argv", ["run.py", "--dataset", str(dataset), "--out", str(tmp_path / "out"), "--max-cost", "1.5"]
    )

    run_module.main()

    assert processed == ["0.pdf", "1.pdf"]
    output = capsys.readouterr().out
    assert "cumul 2.0000 $" in output
    assert "Budget de 1.50 $ atteint" in output
    assert (tmp_path / "out" / "claude-sonnet-5.json").exists()
