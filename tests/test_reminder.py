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
