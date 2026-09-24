from datetime import date

import pytest

from agent_factures.tools.reminder import draft_reminder
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)


def test_reminder_is_addressed_to_the_customer():
    invoice = make_invoice(
        direction="emise",
        supplier="Atelier Lumière SAS",
        customer="Hôtel Bellevue",
        number="AL-042",
        due_date=date(2026, 9, 10),
    )
    text = draft_reminder(invoice, TODAY)
    assert "AL-042" in text
    assert "Hôtel Bellevue" in text
    assert "120,00 €" in text
    assert "10/09/2026" in text
    assert "14 jours" in text
    assert "Atelier Lumière SAS" in text


def test_reminder_refuses_received_invoices():
    with pytest.raises(ValueError, match="émise"):
        draft_reminder(make_invoice(direction="recue"), TODAY)


def test_correction_request_lists_each_amount_error_for_the_supplier():
    from decimal import Decimal

    from agent_factures.extraction.models import Issue
    from agent_factures.tools.reminder import draft_correction_request

    invoice = make_invoice(number="TN-902", supplier="TechNet Services", vat_amount=Decimal("25.00"))
    issues = [
        Issue(code="TOTAL_INCOHERENT", message="HT + TVA = 125,00 € mais le TTC indiqué est 120,00 €."),
        Issue(code="DOUBLON", message="Pièce déjà enregistrée."),
    ]
    text = draft_correction_request(invoice, issues)
    assert text.startswith("À : TechNet Services")
    assert "TN-902" in text
    assert "HT + TVA = 125,00 €" in text
    assert "Pièce déjà enregistrée" not in text
    assert "facture rectificative" in text
    assert "Atelier Lumière SAS" in text


def test_correction_request_is_only_for_received_invoices_with_amount_errors():
    from agent_factures.extraction.models import Issue
    from agent_factures.tools.reminder import AMOUNT_ERROR_CODES, draft_correction_request

    assert AMOUNT_ERROR_CODES == {"TOTAL_INCOHERENT", "LIGNES_INCOHERENTES"}
    amount_issue = [Issue(code="LIGNES_INCOHERENTES", message="Somme des lignes fausse.")]
    with pytest.raises(ValueError, match="reçue"):
        draft_correction_request(make_invoice(direction="emise"), amount_issue)
    with pytest.raises(ValueError, match="montant"):
        draft_correction_request(make_invoice(), [Issue(code="DOUBLON", message="x")])
