import json
from collections import Counter
from decimal import Decimal

from evals.generate import build_specs, generate


def test_dataset_composition_matches_spec():
    specs = build_specs()
    assert len(specs) == 20
    issues = Counter(code for s in specs for code in s["expected_issues"])
    assert issues["DOUBLON"] == 2
    assert issues["TOTAL_INCOHERENT"] == 2
    assert issues["MONTANT_INHABITUEL"] == 1
    assert sum(1 for s in specs if s["invoice"] and s["invoice"]["doc_type"] == "devis") == 2
    assert sum(1 for s in specs if s["invoice"] is None) == 1
    assert sum(1 for s in specs if s["file"].endswith(".png")) == 1
    issued = [s for s in specs if s["invoice"] and s["invoice"]["direction"] == "emise"]
    assert len(issued) == 2
    assert sum(1 for s in issued if "ECHEANCE_DEPASSEE" in s["expected_issues"]) == 1


def test_statuses_follow_issues():
    for s in build_specs():
        if s["invoice"] is None:
            assert s["expected_status"] == "a_revoir"
        elif s["expected_issues"]:
            assert s["expected_status"] == "anomalie"
        else:
            assert s["expected_status"] == "ok"


def test_consistent_documents_add_up():
    for s in build_specs():
        inv = s["invoice"]
        if inv and "TOTAL_INCOHERENT" not in s["expected_issues"]:
            total = Decimal(inv["amount_excl_tax"]) + Decimal(inv["vat_amount"])
            assert total == Decimal(inv["amount_incl_tax"]), s["file"]


def test_generate_writes_files_and_expected_json(tmp_path):
    generate(tmp_path)
    expected = json.loads((tmp_path / "expected.json").read_text())
    assert expected["today"] == "2026-09-24"
    for doc in expected["documents"]:
        path = tmp_path / doc["file"]
        assert path.exists() and path.stat().st_size > 500, doc["file"]
