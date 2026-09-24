from datetime import date

from agent_factures.storage.action_log import ActionLog
from agent_factures.storage.db import connect, supplier_key
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice


def make_repo() -> InvoiceRepository:
    return InvoiceRepository(connect())


def test_supplier_key_normalizes_case_and_spaces():
    assert supplier_key("  Bureau   PLUS sarl ") == "bureau plus sarl"


def test_add_then_get_roundtrip():
    repo = make_repo()
    invoice = make_invoice()
    invoice_id = repo.add(invoice, source_file="inbox/f1.pdf")
    stored = repo.get(invoice_id)
    assert stored is not None
    assert stored.invoice == invoice
    assert stored.source_file == "inbox/f1.pdf"
    assert repo.get(9999) is None


def test_find_by_supplier_and_number_ignores_supplier_case():
    repo = make_repo()
    repo.add(make_invoice(supplier="Bureau Plus SARL", number="F-001"), "a.pdf")
    repo.add(make_invoice(supplier="Bureau Plus SARL", number="F-002"), "b.pdf")
    found = repo.find_by_supplier_and_number("bureau plus sarl", "F-001")
    assert [s.source_file for s in found] == ["a.pdf"]


def test_list_by_supplier():
    repo = make_repo()
    repo.add(make_invoice(supplier="A", number="1"), "a.pdf")
    repo.add(make_invoice(supplier="B", number="2"), "b.pdf")
    repo.add(make_invoice(supplier="a", number="3"), "c.pdf")
    assert [s.invoice.number for s in repo.list_by_supplier("A")] == ["1", "3"]


def test_list_overdue_only_returns_invoices_past_due():
    repo = make_repo()
    repo.add(make_invoice(number="late", due_date=date(2026, 9, 1)), "late.pdf")
    repo.add(make_invoice(number="future", due_date=date(2026, 12, 1)), "future.pdf")
    repo.add(make_invoice(number="nodue", due_date=None), "nodue.pdf")
    repo.add(make_invoice(number="quote", doc_type="devis", due_date=date(2026, 9, 1)), "quote.pdf")
    overdue = repo.list_overdue(date(2026, 9, 24))
    assert [s.invoice.number for s in overdue] == ["late"]


def test_list_overdue_can_filter_by_direction():
    repo = make_repo()
    repo.add(make_invoice(number="to-pay", due_date=date(2026, 9, 1)), "a.pdf")
    repo.add(make_invoice(number="to-collect", direction="emise", due_date=date(2026, 9, 2)), "b.pdf")
    today = date(2026, 9, 24)
    assert [s.invoice.number for s in repo.list_overdue(today, direction="recue")] == ["to-pay"]
    assert [s.invoice.number for s in repo.list_overdue(today, direction="emise")] == ["to-collect"]
    assert len(repo.list_overdue(today)) == 2


def test_list_all_in_insertion_order():
    repo = make_repo()
    repo.add(make_invoice(number="1"), "1.pdf")
    repo.add(make_invoice(number="2"), "2.pdf")
    assert [s.invoice.number for s in repo.list_all()] == ["1", "2"]


def test_action_log_records_and_lists():
    log = ActionLog(connect())
    log.record("f1.pdf", "analyse", {"statut": "ok", "cout_usd": 0.01})
    log.record("f2.pdf", "analyse")
    log.record("f1.pdf", "accepte", {"id": 1})
    entries = log.list_for_document("f1.pdf")
    assert [e.action for e in entries] == ["analyse", "accepte"]
    assert entries[0].detail == {"statut": "ok", "cout_usd": 0.01}
    assert [e.document for e in log.list_recent(limit=2)] == ["f1.pdf", "f2.pdf"]
