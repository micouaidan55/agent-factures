"""Lance l'agent sur le jeu d'évaluation. ATTENTION : appelle l'API Claude (payant, quelques centimes).

Usage : uv run python -m evals.run --model claude-sonnet-5
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from agent_factures.agent.loop import DEFAULT_MODEL, MODELS, AgentResult, InvoiceAgent
from agent_factures.extraction.models import Invoice
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from evals.scoring import DocOutcome, summarize, to_markdown

ROOT = Path(__file__).parent


def ground_truth_invoice(doc: dict) -> Invoice | None:
    """Facture de référence (attendue) pour un document accepté.

    On enregistre celle-ci plutôt que l'extraction du modèle : un humain qui accepte une
    pièce corrige d'abord ses champs, il ne l'enregistre pas telle quelle. Sans ça, une
    extraction légèrement imparfaite pour un document accepté ferait disparaître en
    silence les détections DOUBLON / MONTANT_INHABITUEL des documents suivants qui s'y
    comparent (fournisseur + numéro, moyenne des montants).
    """
    if doc["invoice"] is None:
        return None
    return Invoice.model_validate(doc["invoice"])


def doc_result_json(doc: dict, result: AgentResult, elapsed: float) -> dict:
    """Détail JSON d'un document traité, pour results/<model>.json."""
    return {
        "file": doc["file"],
        "expected_status": doc["expected_status"],
        "status": result.verdict.status.value,
        "explication": result.verdict.explanation,
        "expected_issues": doc["expected_issues"],
        "issues": sorted(issue.code for issue in result.issues),
        "invoice": result.invoice.model_dump(mode="json") if result.invoice is not None else None,
        "cout_usd": result.cost_usd,
        "secondes": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Clé d'API Claude manquante : renseigne ANTHROPIC_API_KEY dans le fichier .env avant de lancer l'évaluation.")
        sys.exit(1)

    expected = json.loads((args.dataset / "expected.json").read_text())
    repo = InvoiceRepository(connect())
    agent = InvoiceAgent(
        client=anthropic.Anthropic(), repo=repo, model=args.model, today=date.fromisoformat(expected["today"])
    )

    outcomes = []
    details = []
    total_cost = 0.0
    for doc in expected["documents"]:
        path = args.dataset / doc["file"]
        started = time.perf_counter()
        result = agent.process(path)
        elapsed = time.perf_counter() - started
        issues = {issue.code for issue in result.issues}
        print(f"{doc['file']:<35} {result.verdict.status.value:<9} {sorted(issues)} {elapsed:.1f}s")
        outcomes.append(
            DocOutcome(
                file=doc["file"], expected=doc, status=result.verdict.status.value, issues=issues,
                invoice=result.invoice, cost_usd=result.cost_usd, seconds=elapsed,
            )
        )
        details.append(doc_result_json(doc, result, elapsed))
        if result.cost_usd is not None:
            total_cost += result.cost_usd
        if doc["accept"]:
            repo.add(ground_truth_invoice(doc), source_file=doc["file"])

    report = to_markdown(args.model, summarize(outcomes))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.model}.md").write_text(report)
    (args.out / f"{args.model}.json").write_text(json.dumps(details, ensure_ascii=False, indent=2))
    print("\n" + report)
    print(f"Coût total de l'évaluation : {total_cost:.4f} $")


if __name__ == "__main__":
    main()
