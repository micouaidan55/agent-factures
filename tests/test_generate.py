import json
import re
from collections import Counter
from decimal import Decimal

from evals.generate import build_specs, generate


def test_dataset_composition_matches_spec():
    specs = build_specs()
    assert len(specs) == 40
    assert len({s["file"] for s in specs}) == 40
    issues = Counter(code for s in specs for code in s["expected_issues"])
    assert issues["DOUBLON"] == 3
    assert issues["TOTAL_INCOHERENT"] == 3
    assert issues["LIGNES_INCOHERENTES"] == 1
    assert issues["MONTANT_INHABITUEL"] == 2
    assert sum(1 for s in specs if s["invoice"] and s["invoice"]["doc_type"] == "devis") == 3
    assert sum(1 for s in specs if s["invoice"] is None) == 3
    assert sum(1 for s in specs if s["file"].endswith(".png")) == 3
    issued = [s for s in specs if s["invoice"] and s["invoice"]["direction"] == "emise"]
    assert len(issued) == 5
    assert sum(1 for s in issued if "ECHEANCE_DEPASSEE" in s["expected_issues"]) == 2


def test_dataset_covers_the_realistic_cases():
    specs = build_specs()
    invoices = [s for s in specs if s["invoice"]]
    assert any(len({line[3] for line in s["lines"]}) > 1 for s in invoices), "facture multi-taux de TVA"
    assert any(s["invoice"]["doc_type"] == "facture" and s["invoice"]["due_date"] is None for s in invoices)
    assert sum(1 for s in specs if s.get("lang") == "en") == 2
    assert any(s.get("layout") == 2 for s in specs), "mise en page en tableau avec pied de page"
    assert any(s.get("scan") == "degrade" for s in specs)
    numbers = [s["invoice"]["number"] for s in invoices]
    assert "F-2026-118" in numbers and "F2026-118" in numbers, "doublon avec un numéro formaté autrement"


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


def test_expected_lines_add_up_to_net_total_unless_flagged():
    for s in build_specs():
        inv = s["invoice"]
        if not inv:
            continue
        lines_total = sum(Decimal(line["total"]) for line in inv["lines"])
        if "LIGNES_INCOHERENTES" in s["expected_issues"]:
            assert lines_total != Decimal(inv["amount_excl_tax"]), s["file"]
        else:
            assert lines_total == Decimal(inv["amount_excl_tax"]), s["file"]


def test_generate_writes_files_and_expected_json(tmp_path):
    generate(tmp_path)
    expected = json.loads((tmp_path / "expected.json").read_text())
    assert expected["today"] == "2026-09-24"
    assert len(expected["documents"]) == 40
    for doc in expected["documents"]:
        path = tmp_path / doc["file"]
        assert path.exists() and path.stat().st_size > 500, doc["file"]
    multipage = next(p for p in tmp_path.glob("*multipage*.pdf"))
    assert len(re.findall(rb"/Type /Page[^s]", multipage.read_bytes())) == 2
