"""Vérifications qui s'appuient sur les factures déjà enregistrées (lecture seule)."""

from decimal import Decimal

from pydantic import BaseModel

from agent_factures.extraction.models import Direction, DocumentType, Invoice, Issue
from agent_factures.storage.repository import InvoiceRepository, StoredInvoice

MIN_HISTORY = 3
UNUSUAL_FACTOR = Decimal("3")


class SupplierStats(BaseModel):
    supplier: str
    count: int
    average_incl_tax: Decimal | None


def find_duplicates(repo: InvoiceRepository, supplier: str, number: str) -> list[StoredInvoice]:
    return repo.find_by_supplier_and_number(supplier, number)


def get_supplier_history(repo: InvoiceRepository, supplier: str) -> SupplierStats:
    invoices = [
        s.invoice
        for s in repo.list_by_supplier(supplier)
        if s.invoice.doc_type is DocumentType.INVOICE and s.invoice.direction is Direction.RECEIVED
    ]
    if not invoices:
        return SupplierStats(supplier=supplier, count=0, average_incl_tax=None)
    total = sum((i.amount_incl_tax for i in invoices), Decimal("0"))
    return SupplierStats(supplier=supplier, count=len(invoices), average_incl_tax=total / len(invoices))


def check_unusual_amount(invoice: Invoice, stats: SupplierStats) -> Issue | None:
    if invoice.direction is Direction.ISSUED or stats.count < MIN_HISTORY or stats.average_incl_tax is None:
        return None
    threshold = stats.average_incl_tax * UNUSUAL_FACTOR
    if invoice.amount_incl_tax <= threshold:
        return None
    return Issue(
        code="MONTANT_INHABITUEL",
        message=(
            f"Montant de {invoice.amount_incl_tax} € TTC, plus de 3 fois la moyenne "
            f"({stats.average_incl_tax:.2f} €) des {stats.count} factures précédentes de ce fournisseur."
        ),
    )
