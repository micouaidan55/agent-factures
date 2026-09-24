"""Accès aux factures enregistrées."""

import sqlite3
from datetime import date

from pydantic import BaseModel

from agent_factures.extraction.models import Direction, DocumentType, Invoice
from agent_factures.storage.db import number_key, supplier_key


class StoredInvoice(BaseModel):
    id: int
    invoice: Invoice
    source_file: str
    paid_at: date | None = None


class InvoiceRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, invoice: Invoice, source_file: str) -> int:
        cursor = self._conn.execute(
            "INSERT INTO invoices (supplier_key, number, doc_type, direction, due_date, amount_incl_tax, data, source_file)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                supplier_key(invoice.supplier),
                number_key(invoice.number),
                invoice.doc_type.value,
                invoice.direction.value,
                invoice.due_date.isoformat() if invoice.due_date else None,
                str(invoice.amount_incl_tax),
                invoice.model_dump_json(),
                source_file,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get(self, invoice_id: int) -> StoredInvoice | None:
        rows = self._select("WHERE id = ?", (invoice_id,))
        return rows[0] if rows else None

    def find_by_supplier_and_number(self, supplier: str, number: str) -> list[StoredInvoice]:
        return self._select("WHERE supplier_key = ? AND number = ?", (supplier_key(supplier), number_key(number)))

    def list_by_supplier(self, supplier: str) -> list[StoredInvoice]:
        return self._select("WHERE supplier_key = ?", (supplier_key(supplier),))

    def mark_paid(self, invoice_id: int, paid_on: date) -> None:
        self._conn.execute("UPDATE invoices SET paid_at = ? WHERE id = ?", (paid_on.isoformat(), invoice_id))
        self._conn.commit()

    def list_unpaid(self, direction: Direction) -> list[StoredInvoice]:
        """Factures (hors devis) non payées d'un sens donné, par échéance croissante, sans échéance en dernier."""
        return self._select(
            "WHERE doc_type = ? AND direction = ? AND paid_at IS NULL",
            (DocumentType.INVOICE.value, Direction(direction).value),
            order="due_date IS NULL, due_date, id",
        )

    def list_overdue(self, today: date, direction: Direction | None = None) -> list[StoredInvoice]:
        where = "WHERE doc_type = ? AND paid_at IS NULL AND due_date IS NOT NULL AND due_date < ?"
        params: tuple = (DocumentType.INVOICE.value, today.isoformat())
        if direction is not None:
            where += " AND direction = ?"
            params += (Direction(direction).value,)
        return self._select(where, params, order="due_date, id")

    def list_all(self) -> list[StoredInvoice]:
        return self._select("", ())

    def _select(self, where: str, params: tuple, order: str = "id") -> list[StoredInvoice]:
        rows = self._conn.execute(
            f"SELECT id, data, source_file, paid_at FROM invoices {where} ORDER BY {order}", params
        )
        return [
            StoredInvoice(
                id=row["id"],
                invoice=Invoice.model_validate_json(row["data"]),
                source_file=row["source_file"],
                paid_at=row["paid_at"],
            )
            for row in rows
        ]
