from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_factures.extraction.models import Direction, DocumentType, Invoice, Status, Verdict
from tests.factories import make_invoice


def test_invoice_parses_claude_style_payload():
    invoice = Invoice.model_validate(
        {
            "doc_type": "facture",
            "direction": "emise",
            "supplier": "Bureau Plus SARL",
            "number": "F-2026-101",
            "issue_date": "2026-09-01",
            "due_date": None,
            "amount_excl_tax": 100.1,
            "vat_amount": 20.02,
            "amount_incl_tax": 120.12,
        }
    )
    assert invoice.doc_type is DocumentType.INVOICE
    assert invoice.direction is Direction.ISSUED
    assert invoice.customer is None
    assert invoice.issue_date == date(2026, 9, 1)
    assert invoice.due_date is None
    assert invoice.amount_excl_tax == Decimal("100.1")
    assert invoice.currency == "EUR"
    assert invoice.lines == []


def test_invoice_rejects_empty_supplier():
    with pytest.raises(ValidationError):
        make_invoice(supplier="")


def test_invoice_rejects_unknown_doc_type():
    with pytest.raises(ValidationError):
        make_invoice(doc_type="bon de commande")


def test_invoice_requires_a_known_direction():
    with pytest.raises(ValidationError):
        make_invoice(direction="sortante")
    with pytest.raises(ValidationError):
        make_invoice(direction=None)


def test_verdict_accepts_known_status_and_rejects_others():
    assert Verdict(status="anomalie", explanation="TVA incohérente").status is Status.ANOMALY
    with pytest.raises(ValidationError):
        Verdict(status="parfait", explanation="?")
    with pytest.raises(ValidationError):
        Verdict(status="ok", explanation="")
