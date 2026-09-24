from datetime import date
from decimal import Decimal

from agent_factures.tools.checks import check_amounts, check_due_date
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)


def test_consistent_invoice_has_no_amount_issue():
    assert check_amounts(make_invoice()) == []


def test_rounding_within_tolerance_is_accepted():
    assert check_amounts(make_invoice(amount_incl_tax=Decimal("120.02"))) == []


def test_total_mismatch_is_flagged():
    issues = check_amounts(make_invoice(vat_amount=Decimal("25.00")))
    assert [i.code for i in issues] == ["TOTAL_INCOHERENT"]
    assert "125" in issues[0].message and "120" in issues[0].message


def test_lines_mismatch_is_flagged():
    invoice = make_invoice(
        amount_excl_tax=Decimal("150.00"), vat_amount=Decimal("30.00"), amount_incl_tax=Decimal("180.00")
    )
    assert [i.code for i in check_amounts(invoice)] == ["LIGNES_INCOHERENTES"]


def test_invoice_without_lines_skips_line_check():
    assert check_amounts(make_invoice(lines=[])) == []


def test_overdue_received_invoice_is_to_pay():
    issue = check_due_date(make_invoice(due_date=date(2026, 9, 10)), TODAY)
    assert issue is not None
    assert issue.code == "ECHEANCE_DEPASSEE"
    assert "14 jours" in issue.message
    assert "à payer" in issue.message


def test_overdue_issued_invoice_is_unpaid_by_customer():
    issue = check_due_date(make_invoice(direction="emise", due_date=date(2026, 9, 10)), TODAY)
    assert issue is not None
    assert issue.code == "ECHEANCE_DEPASSEE"
    assert "impayé client" in issue.message


def test_due_today_or_later_is_fine():
    assert check_due_date(make_invoice(due_date=TODAY), TODAY) is None


def test_quote_and_missing_due_date_are_ignored():
    assert check_due_date(make_invoice(doc_type="devis", due_date=date(2026, 1, 1)), TODAY) is None
    assert check_due_date(make_invoice(due_date=None), TODAY) is None
