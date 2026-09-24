"""Exports tabulaires des pièces enregistrées."""

from io import BytesIO

import pandas as pd

from agent_factures.storage.repository import StoredInvoice

COLUMNS = [
    "id", "type", "sens", "emetteur", "destinataire", "numero", "date_emission", "echeance",
    "montant_ht", "tva", "montant_ttc", "devise", "fichier",
]


def to_rows(stored: list[StoredInvoice]) -> list[dict]:
    return [
        {
            "id": s.id,
            "type": s.invoice.doc_type.value,
            "sens": s.invoice.direction.value,
            "emetteur": s.invoice.supplier,
            "destinataire": s.invoice.customer,
            "numero": s.invoice.number,
            "date_emission": s.invoice.issue_date.isoformat(),
            "echeance": s.invoice.due_date.isoformat() if s.invoice.due_date else None,
            "montant_ht": float(s.invoice.amount_excl_tax),
            "tva": float(s.invoice.vat_amount),
            "montant_ttc": float(s.invoice.amount_incl_tax),
            "devise": s.invoice.currency,
            "fichier": s.source_file,
        }
        for s in stored
    ]


def _frame(stored: list[StoredInvoice]) -> pd.DataFrame:
    return pd.DataFrame(to_rows(stored), columns=COLUMNS)


def to_csv_bytes(stored: list[StoredInvoice]) -> bytes:
    return _frame(stored).to_csv(index=False, sep=";").encode("utf-8-sig")


def to_excel_bytes(stored: list[StoredInvoice]) -> bytes:
    buffer = BytesIO()
    _frame(stored).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()
