from datetime import date

from agent_factures.storage.db import connect
from agent_factures.storage.ledger import build_ledger
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)


def test_ledger_sorts_unpaid_invoices_into_three_lists():
    repo = InvoiceRepository(connect())
    repo.add(make_invoice(number="due-soon", due_date=date(2026, 10, 1)), "a.pdf")
    repo.add(make_invoice(number="no-due", due_date=None), "b.pdf")
    repo.add(make_invoice(number="late-2", due_date=date(2026, 9, 20)), "c.pdf")
    repo.add(make_invoice(number="late-1", due_date=date(2026, 9, 1)), "d.pdf")
    paid = repo.add(make_invoice(number="paid", due_date=date(2026, 9, 1)), "e.pdf")
    repo.add(make_invoice(number="quote", doc_type="devis"), "f.pdf")
    repo.add(make_invoice(number="client-late", direction="emise", due_date=date(2026, 9, 10)), "g.pdf")
    repo.add(make_invoice(number="client-ok", direction="emise", due_date=date(2026, 10, 10)), "h.pdf")
    repo.mark_paid(paid, TODAY)

    ledger = build_ledger(repo, TODAY)

    assert [s.invoice.number for s in ledger.to_pay] == ["due-soon", "no-due"]
    assert [s.invoice.number for s in ledger.overdue] == ["late-1", "late-2"]
    assert [s.invoice.number for s in ledger.unpaid_customers] == ["client-late", "client-ok"]
    assert [s.invoice.number for s in ledger.paid] == ["paid"]
    assert ledger.days_late(ledger.overdue[0], TODAY) == 23
    assert ledger.days_late(ledger.unpaid_customers[1], TODAY) == 0


def test_invoice_due_today_is_not_overdue():
    repo = InvoiceRepository(connect())
    repo.add(make_invoice(number="today", due_date=TODAY), "a.pdf")
    ledger = build_ledger(repo, TODAY)
    assert [s.invoice.number for s in ledger.to_pay] == ["today"]
    assert ledger.overdue == []
