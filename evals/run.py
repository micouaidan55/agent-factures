"""Lance l'agent sur le jeu d'évaluation. ATTENTION : appelle l'API Claude (payant, quelques centimes).

Usage : uv run python -m evals.run --model claude-sonnet-5
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from agent_factures.agent.loop import DEFAULT_MODEL, MODELS, InvoiceAgent
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from evals.scoring import DocOutcome, summarize, to_markdown

ROOT = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    load_dotenv()
    expected = json.loads((args.dataset / "expected.json").read_text())
    repo = InvoiceRepository(connect())
    agent = InvoiceAgent(
        client=anthropic.Anthropic(), repo=repo, model=args.model, today=date.fromisoformat(expected["today"])
    )

    outcomes = []
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
        if doc["accept"] and result.invoice is not None:
            repo.add(result.invoice, source_file=doc["file"])

    report = to_markdown(args.model, summarize(outcomes))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.model}.md").write_text(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
