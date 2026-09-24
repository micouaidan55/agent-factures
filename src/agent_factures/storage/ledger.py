"""Classement des factures non payées : à payer, échéance dépassée, clients impayés."""

from dataclasses import dataclass
from datetime import date

from agent_factures.extraction.models import Direction
from agent_factures.storage.repository import InvoiceRepository, StoredInvoice


@dataclass
class Ledger:
    to_pay: list[StoredInvoice]
    overdue: list[StoredInvoice]
    unpaid_customers: list[StoredInvoice]

    @staticmethod
    def days_late(stored: StoredInvoice, today: date) -> int:
        due = stored.invoice.due_date
        return max((today - due).days, 0) if due else 0


def _is_overdue(stored: StoredInvoice, today: date) -> bool:
    return stored.invoice.due_date is not None and stored.invoice.due_date < today


def build_ledger(repo: InvoiceRepository, today: date) -> Ledger:
    received = repo.list_unpaid(direction=Direction.RECEIVED)
    return Ledger(
        to_pay=[s for s in received if not _is_overdue(s, today)],
        overdue=[s for s in received if _is_overdue(s, today)],
        unpaid_customers=repo.list_unpaid(direction=Direction.ISSUED),
    )
