from datetime import date
from decimal import Decimal

from agent_factures.extraction.models import Invoice


def make_invoice(**overrides) -> Invoice:
    data = {
        "doc_type": "facture",
        "direction": "recue",
        "supplier": "Bureau Plus SARL",
        "customer": "Atelier Lumière SAS",
        "number": "F-001",
        "issue_date": date(2026, 9, 1),
        "due_date": date(2026, 10, 1),
        "amount_excl_tax": Decimal("100.00"),
        "vat_amount": Decimal("20.00"),
        "amount_incl_tax": Decimal("120.00"),
        "lines": [
            {"description": "Ramettes de papier", "quantity": "10", "unit_price": "10.00", "total": "100.00"}
        ],
    }
    data.update(overrides)
    return Invoice.model_validate(data)
