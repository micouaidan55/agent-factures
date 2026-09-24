from decimal import Decimal

from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from agent_factures.tools.history import (
    SupplierStats,
    check_unusual_amount,
    find_duplicates,
    get_supplier_history,
)
from tests.factories import make_invoice


def repo_with(*invoices) -> InvoiceRepository:
    repo = InvoiceRepository(connect())
    for i, invoice in enumerate(invoices):
        repo.add(invoice, f"{i}.pdf")
    return repo


def test_find_duplicates_matches_supplier_and_number():
    repo = repo_with(make_invoice(number="F-1"), make_invoice(number="F-2"))
    assert len(find_duplicates(repo, "BUREAU PLUS SARL", "F-1")) == 1
    assert find_duplicates(repo, "Bureau Plus SARL", "F-3") == []


def test_supplier_history_averages_received_invoices_only():
    repo = repo_with(
        make_invoice(number="1", amount_incl_tax=Decimal("100")),
        make_invoice(number="2", amount_incl_tax=Decimal("110")),
        make_invoice(number="3", amount_incl_tax=Decimal("120")),
        make_invoice(number="D1", doc_type="devis", amount_incl_tax=Decimal("9999")),
        make_invoice(number="E1", direction="emise", amount_incl_tax=Decimal("9999")),
    )
    stats = get_supplier_history(repo, "Bureau Plus SARL")
    assert stats.count == 3
    assert stats.average_incl_tax == Decimal("110")


def test_unknown_supplier_has_empty_history():
    stats = get_supplier_history(repo_with(), "Inconnu")
    assert stats == SupplierStats(supplier="Inconnu", count=0, average_incl_tax=None)


def test_unusual_amount_requires_three_invoices_and_strictly_more_than_triple():
    stats = SupplierStats(supplier="X", count=3, average_incl_tax=Decimal("100"))
    issue = check_unusual_amount(make_invoice(amount_incl_tax=Decimal("301")), stats)
    assert issue is not None and issue.code == "MONTANT_INHABITUEL"
    assert check_unusual_amount(make_invoice(amount_incl_tax=Decimal("300")), stats) is None
    short = SupplierStats(supplier="X", count=2, average_incl_tax=Decimal("100"))
    assert check_unusual_amount(make_invoice(amount_incl_tax=Decimal("1000")), short) is None


def test_issued_invoices_are_never_unusual():
    stats = SupplierStats(supplier="X", count=5, average_incl_tax=Decimal("100"))
    assert check_unusual_amount(make_invoice(direction="emise", amount_incl_tax=Decimal("5000")), stats) is None
