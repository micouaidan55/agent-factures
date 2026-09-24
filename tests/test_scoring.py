import json

import pytest

from evals.scoring import DocOutcome, field_matches, summarize, to_markdown
from tests.factories import make_invoice

EXPECTED_INVOICE = json.loads(
    make_invoice().model_dump_json(include={"doc_type", "direction", "supplier", "customer", "number", "issue_date",
                                            "due_date", "amount_excl_tax", "vat_amount", "amount_incl_tax"})
)


def outcome(**kw) -> DocOutcome:
    base = dict(file="f.pdf", expected={"expected_status": "ok", "expected_issues": [], "invoice": EXPECTED_INVOICE},
                status="ok", issues=set(), invoice=make_invoice(), cost_usd=0.01, seconds=2.0)
    base.update(kw)
    return DocOutcome(**base)


def test_field_matching_rules():
    assert field_matches("supplier", "Bureau Plus SARL", "  BUREAU plus sarl ")
    assert field_matches("amount_incl_tax", "120.00", 120.005)
    assert not field_matches("amount_incl_tax", "120.00", 120.02)
    assert field_matches("due_date", None, None)
    assert not field_matches("due_date", "2026-10-01", None)
    assert field_matches("issue_date", "2026-09-01", "2026-09-01")


def test_perfect_run():
    summary = summarize([outcome()])
    assert summary["overall_field_accuracy"] == 1.0
    assert summary["verdict_accuracy"] == 1.0
    assert summary["documents"] == 1


def test_missing_extraction_counts_as_all_fields_wrong():
    summary = summarize([outcome(invoice=None, status="a_revoir")])
    assert summary["overall_field_accuracy"] == 0.0
    assert summary["verdict_accuracy"] == 0.0


def test_detection_precision_and_recall():
    expected = {"expected_status": "anomalie", "expected_issues": ["DOUBLON", "ECHEANCE_DEPASSEE"], "invoice": EXPECTED_INVOICE}
    summary = summarize([outcome(expected=expected, status="anomalie", issues={"DOUBLON", "TOTAL_INCOHERENT"})])
    assert summary["detection_precision"] == pytest.approx(0.5)
    assert summary["detection_recall"] == pytest.approx(0.5)


def test_letter_is_excluded_from_field_accuracy():
    letter = outcome(expected={"expected_status": "a_revoir", "expected_issues": [], "invoice": None},
                     status="a_revoir", invoice=None)
    summary = summarize([outcome(), letter])
    assert summary["overall_field_accuracy"] == 1.0
    assert summary["verdict_accuracy"] == 1.0


def test_markdown_contains_headline_numbers():
    text = to_markdown("claude-sonnet-5", summarize([outcome()]))
    assert "claude-sonnet-5" in text
    assert "100,0 %" in text
