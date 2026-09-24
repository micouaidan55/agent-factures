from io import BytesIO

import pandas as pd

from agent_factures.storage.export import COLUMNS, to_csv_bytes, to_excel_bytes, to_rows
from agent_factures.storage.repository import StoredInvoice
from tests.factories import make_invoice

STORED = [
    StoredInvoice(id=1, invoice=make_invoice(number="F-1"), source_file="a.pdf"),
    StoredInvoice(id=2, invoice=make_invoice(number="F-2", due_date=None), source_file="b.pdf"),
]


def test_rows_are_flat_and_ordered():
    rows = to_rows(STORED)
    assert list(rows[0]) == COLUMNS
    assert rows[0]["numero"] == "F-1"
    assert rows[0]["sens"] == "recue"
    assert rows[0]["destinataire"] == "Atelier Lumière SAS"
    assert rows[0]["montant_ttc"] == 120.0
    assert rows[1]["echeance"] is None


def test_csv_uses_semicolons_and_bom():
    content = to_csv_bytes(STORED)
    assert content.startswith("﻿".encode("utf-8"))
    header = content.decode("utf-8-sig").splitlines()[0]
    assert header == ";".join(COLUMNS)


def test_excel_roundtrip():
    frame = pd.read_excel(BytesIO(to_excel_bytes(STORED)))
    assert list(frame.columns) == COLUMNS
    assert frame["numero"].tolist() == ["F-1", "F-2"]
