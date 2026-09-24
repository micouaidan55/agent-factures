import json
from datetime import date
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from agent_factures.agent.loop import InvoiceAgent
from agent_factures.extraction.models import Status
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice
from tests.fakes import FakeClient, reply, tool_use

TODAY = date(2026, 9, 24)
VALID = json.loads(make_invoice().model_dump_json())


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "facture.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def run(responses, path, **kwargs):
    repo = InvoiceRepository(connect())
    client = FakeClient(responses)
    agent = InvoiceAgent(client=client, repo=repo, today=TODAY, **kwargs)
    return agent.process(path), client, repo


def test_happy_path(pdf):
    result, client, repo = run(
        [
            reply(tool_use("submit_extraction", VALID)),
            reply(tool_use("check_amounts", {}, id="a"), tool_use("check_due_date", {}, id="b")),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Facture conforme."})),
        ],
        pdf,
    )
    assert result.verdict.status is Status.OK
    assert result.invoice == make_invoice()
    # find_duplicates and get_supplier_history weren't called by Claude: the loop runs them
    # itself after the verdict (F3) so a skipped check never hides an anomaly.
    assert [c.name for c in result.trace] == [
        "submit_extraction", "check_amounts", "check_due_date", "submit_verdict",
        "find_duplicates", "get_supplier_history",
    ]
    assert (result.input_tokens, result.output_tokens) == (300, 150)
    assert result.cost_usd == pytest.approx((300 * 2.0 + 150 * 10.0) / 1_000_000)
    assert len(client.calls) == 3
    first = client.calls[0]
    assert first["model"] == "claude-sonnet-5"
    assert "Atelier Lumière SAS" in first["system"]
    assert first["messages"][0]["content"][0]["type"] == "document"
    results_message = client.calls[2]["messages"][-1]
    assert results_message["role"] == "user"
    assert [r["tool_use_id"] for r in results_message["content"]] == ["a", "b"]
    assert repo.list_all() == []


def test_invalid_extraction_is_retried(pdf):
    result, _, _ = run(
        [
            reply(tool_use("submit_extraction", {**VALID, "supplier": ""})),
            reply(tool_use("submit_extraction", VALID)),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Conforme."})),
        ],
        pdf,
    )
    assert result.invoice is not None
    assert result.verdict.status is Status.OK
    assert result.trace[0].is_error


def test_two_invalid_extractions_stop_the_loop(pdf):
    bad = {**VALID, "supplier": ""}
    result, client, _ = run([reply(tool_use("submit_extraction", bad)), reply(tool_use("submit_extraction", bad))], pdf)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert result.partial_extraction == bad
    assert len(client.calls) == 2


def test_iteration_limit(pdf):
    result, client, _ = run([reply(tool_use("check_amounts", {})) for _ in range(3)], pdf, max_iterations=3)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "Limite de 3 itérations" in result.verdict.explanation
    assert len(client.calls) == 3


def test_stopping_without_verdict_needs_review(pdf):
    text = SimpleNamespace(type="text", text="J'ai fini.")
    result, _, _ = run([reply(text, stop_reason="end_turn")], pdf)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "sans rendre de verdict" in result.verdict.explanation


def test_api_error_needs_review(pdf):
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    result, _, _ = run([error], pdf)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "Erreur d'API" in result.verdict.explanation


def test_unsupported_file_never_calls_claude(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    result, client, _ = run([], path)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "Format non supporté" in result.verdict.explanation
    assert client.calls == []


def test_ok_verdict_is_downgraded_when_issues_exist(pdf):
    result, _, _ = run(
        [
            reply(tool_use("submit_extraction", {**VALID, "vat_amount": 25})),
            reply(tool_use("check_amounts", {})),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Conforme."})),
        ],
        pdf,
    )
    assert result.verdict.status is Status.ANOMALY
    assert "TOTAL_INCOHERENT" in result.verdict.explanation


def test_company_name_is_configurable(pdf):
    _, client, _ = run(
        [reply(tool_use("submit_verdict", {"status": "a_revoir", "explanation": "Illisible."}))],
        pdf,
        company="Boulangerie Durand",
    )
    assert "Boulangerie Durand" in client.calls[0]["system"]


def test_skipped_check_still_runs_and_catches_duplicate(pdf):
    repo = InvoiceRepository(connect())
    repo.add(make_invoice(), "existing.pdf")
    client = FakeClient(
        [
            reply(tool_use("submit_extraction", VALID)),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Conforme."})),
        ]
    )
    agent = InvoiceAgent(client=client, repo=repo, today=TODAY)
    result = agent.process(pdf)

    assert result.verdict.status is Status.ANOMALY
    assert "DOUBLON" in {issue.code for issue in result.issues}
    assert "find_duplicates" in [c.name for c in result.trace]


def test_unknown_model_has_no_cost(pdf):
    result, _, _ = run(
        [reply(tool_use("submit_verdict", {"status": "a_revoir", "explanation": "Ce n'est pas une facture."}))],
        pdf,
        model="claude-inconnu",
    )
    assert result.cost_usd is None
