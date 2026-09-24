from datetime import date

from agent_factures.storage.action_log import ActionLog
from agent_factures.storage.db import connect, number_key, supplier_key
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


def test_number_key_ignores_case_and_separators():
    assert number_key(" F-2026/118 ") == number_key("f2026.118") == "f2026118"


def test_find_by_supplier_and_number_ignores_number_formatting():
    repo = make_repo()
    repo.add(make_invoice(number="F-2026-118"), "a.pdf")
    assert [s.source_file for s in repo.find_by_supplier_and_number("Bureau Plus SARL", "F2026 118")] == ["a.pdf"]
    assert repo.find_by_supplier_and_number("Bureau Plus SARL", "F-2026-119") == []


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


def test_connect_normalizes_numbers_stored_by_older_versions(tmp_path):
    db_path = str(tmp_path / "old.db")
    conn = connect(db_path)
    InvoiceRepository(conn).add(make_invoice(number="F-2026-118"), "a.pdf")
    conn.execute("UPDATE invoices SET number = 'F-2026-118'")  # format des versions précédentes
    conn.commit()
    conn.close()
    repo = InvoiceRepository(connect(db_path))
    assert len(repo.find_by_supplier_and_number("Bureau Plus SARL", "F2026118")) == 1


def test_mark_paid_records_the_payment_date():
    repo = make_repo()
    invoice_id = repo.add(make_invoice(), "a.pdf")
    assert repo.get(invoice_id).paid_at is None
    repo.mark_paid(invoice_id, date(2026, 9, 24))
    assert repo.get(invoice_id).paid_at == date(2026, 9, 24)


def test_paid_invoices_leave_overdue_and_unpaid_lists():
    repo = make_repo()
    paid = repo.add(make_invoice(number="paid", due_date=date(2026, 9, 1)), "a.pdf")
    repo.add(make_invoice(number="late", due_date=date(2026, 9, 2)), "b.pdf")
    repo.add(make_invoice(number="later", due_date=None), "c.pdf")
    repo.add(make_invoice(number="quote", doc_type="devis"), "d.pdf")
    repo.add(make_invoice(number="issued", direction="emise"), "e.pdf")
    repo.mark_paid(paid, date(2026, 9, 20))
    today = date(2026, 9, 24)
    assert [s.invoice.number for s in repo.list_overdue(today)] == ["late"]
    assert [s.invoice.number for s in repo.list_unpaid(direction="recue")] == ["late", "later"]
    assert [s.invoice.number for s in repo.list_unpaid(direction="emise")] == ["issued"]


def test_connect_adds_the_paid_column_to_older_databases(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "old.db")
    old = sqlite3.connect(db_path)
    old.executescript(
        "CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_key TEXT NOT NULL,"
        " number TEXT NOT NULL, doc_type TEXT NOT NULL, direction TEXT NOT NULL, due_date TEXT,"
        " amount_incl_tax TEXT NOT NULL, data TEXT NOT NULL, source_file TEXT NOT NULL,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')));"
    )
    old.close()
    repo = InvoiceRepository(connect(db_path))
    invoice_id = repo.add(make_invoice(), "a.pdf")
    repo.mark_paid(invoice_id, date(2026, 9, 24))
    assert repo.get(invoice_id).paid_at == date(2026, 9, 24)
