"""Vérifie que le jeu d'évaluation est cohérent avec lui-même, sans appeler l'API :
les contrôles déterministes, appliqués à l'extraction attendue (le "ground truth") de
chaque document dans l'ordre, doivent retrouver exactement les anomalies attendues.
Cela garantit aussi que evals/run.py enregistre bien la bonne pièce (voir F2 : stocker
la facture de référence, pas l'extraction du modèle, pour les documents acceptés)."""

import json
from datetime import date
from pathlib import Path

from agent_factures.agent.executor import ToolExecutor
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from evals.run import ground_truth_invoice

DATASET = Path(__file__).resolve().parent.parent / "evals" / "dataset"


def test_dataset_checks_match_expected_issues_in_order():
    expected = json.loads((DATASET / "expected.json").read_text())
    today = date.fromisoformat(expected["today"])
    repo = InvoiceRepository(connect())

    for doc in expected["documents"]:
        executor = ToolExecutor(repo, today)
        if doc["invoice"] is not None:
            executor.execute("submit_extraction", doc["invoice"])
            executor.execute("check_amounts", {})
            executor.execute("check_due_date", {})
            executor.execute("find_duplicates", {})
            executor.execute("get_supplier_history", {})
        assert {i.code for i in executor.issues} == set(doc["expected_issues"]), doc["file"]

        if doc["accept"]:
            repo.add(ground_truth_invoice(doc), source_file=doc["file"])
