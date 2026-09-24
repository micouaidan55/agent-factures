import json
from datetime import date
from decimal import Decimal

from agent_factures.agent.executor import ToolExecutor
from agent_factures.extraction.models import Status
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)
VALID = json.loads(make_invoice().model_dump_json())


def make_executor(*stored) -> ToolExecutor:
    repo = InvoiceRepository(connect())
    for i, invoice in enumerate(stored):
        repo.add(invoice, f"{i}.pdf")
    return ToolExecutor(repo, TODAY)


def test_unknown_tool_is_an_error():
    executor = make_executor()
    output, is_error = executor.execute("delete_everything", {})
    assert is_error and "inconnu" in output


def test_checks_before_extraction_are_refused():
    executor = make_executor()
    output, is_error = executor.execute("check_amounts", {})
    assert is_error and "submit_extraction" in output


def test_valid_extraction_then_clean_checks():
    executor = make_executor()
    assert executor.execute("submit_extraction", VALID) == ("Extraction enregistrée.", False)
    assert executor.invoice is not None
    output, is_error = executor.execute("check_amounts", {})
    assert not is_error and json.loads(output) == []
    assert executor.issues == []


def test_invalid_extraction_gets_one_retry_then_needs_review():
    executor = make_executor()
    bad = {**VALID, "supplier": ""}
    output, is_error = executor.execute("submit_extraction", bad)
    assert is_error and "corrige" in output
    assert executor.verdict is None
    output, is_error = executor.execute("submit_extraction", bad)
    assert is_error
    assert executor.verdict is not None and executor.verdict.status is Status.NEEDS_REVIEW
    assert executor.partial_extraction == bad
    assert executor.invoice is None


def test_amount_issue_is_collected():
    executor = make_executor()
    executor.execute("submit_extraction", {**VALID, "vat_amount": 25})
    output, _ = executor.execute("check_amounts", {})
    assert json.loads(output)[0]["code"] == "TOTAL_INCOHERENT"
    assert [i.code for i in executor.issues] == ["TOTAL_INCOHERENT"]


def test_duplicate_is_detected():
    executor = make_executor(make_invoice())
    executor.execute("submit_extraction", VALID)
    output, is_error = executor.execute("find_duplicates", {})
    assert not is_error
    assert json.loads(output)["doublons"][0]["fichier"] == "0.pdf"
    assert [i.code for i in executor.issues] == ["DOUBLON"]


def test_supplier_history_flags_unusual_amount():
    history = [make_invoice(number=str(n), amount_incl_tax=Decimal("100")) for n in range(3)]
    executor = make_executor(*history)
    executor.execute("submit_extraction", {**VALID, "amount_excl_tax": 1000, "vat_amount": 200, "amount_incl_tax": 1200, "lines": []})
    output, _ = executor.execute("get_supplier_history", {})
    payload = json.loads(output)
    assert payload["nombre_factures"] == 3
    assert payload["alerte"]["code"] == "MONTANT_INHABITUEL"
    assert [i.code for i in executor.issues] == ["MONTANT_INHABITUEL"]


def test_overdue_is_detected():
    executor = make_executor()
    executor.execute("submit_extraction", {**VALID, "due_date": "2026-09-01"})
    output, _ = executor.execute("check_due_date", {})
    assert json.loads(output)["code"] == "ECHEANCE_DEPASSEE"


def test_same_issue_is_not_collected_twice():
    executor = make_executor()
    executor.execute("submit_extraction", {**VALID, "vat_amount": 25})
    executor.execute("check_amounts", {})
    executor.execute("check_amounts", {})
    assert len(executor.issues) == 1


def test_verdict_validation():
    executor = make_executor()
    output, is_error = executor.execute("submit_verdict", {"status": "parfait", "explanation": "?"})
    assert is_error and executor.verdict is None
    output, is_error = executor.execute("submit_verdict", {"status": "ok", "explanation": "Tout est correct."})
    assert not is_error and executor.verdict.status is Status.OK


def test_every_call_is_traced():
    executor = make_executor()
    executor.execute("check_amounts", {})
    executor.execute("submit_extraction", VALID)
    assert [(c.name, c.is_error) for c in executor.trace] == [("check_amounts", True), ("submit_extraction", False)]


def test_handler_crash_becomes_tool_error():
    executor = make_executor()
    executor.execute("submit_extraction", VALID)

    # Simulate a corrupt repository by replacing list_by_supplier
    def corrupt_list(*args, **kwargs):
        raise RuntimeError("base corrompue")

    executor.repo.list_by_supplier = corrupt_list
    output, is_error = executor.execute("get_supplier_history", {})

    assert is_error is True
    assert "base corrompue" in output
    assert executor.trace[-1].name == "get_supplier_history"
    assert executor.trace[-1].is_error is True
