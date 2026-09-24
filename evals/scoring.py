"""Calcul des métriques d'évaluation (fonctions pures)."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import mean

from agent_factures.extraction.models import Invoice

FIELDS = [
    "doc_type", "direction", "supplier", "customer", "number", "issue_date", "due_date",
    "amount_excl_tax", "vat_amount", "amount_incl_tax",
]
MONEY_FIELDS = {"amount_excl_tax", "vat_amount", "amount_incl_tax"}
MONEY_TOLERANCE = Decimal("0.01")


@dataclass
class DocOutcome:
    file: str
    expected: dict
    status: str
    issues: set[str]
    invoice: Invoice | None
    cost_usd: float | None
    seconds: float


def _normalize(value) -> str:
    return " ".join(str(value).casefold().split())


def field_matches(field: str, expected, actual) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if field in MONEY_FIELDS:
        try:
            return abs(Decimal(str(expected)) - Decimal(str(actual))) <= MONEY_TOLERANCE
        except InvalidOperation:
            return False
    return _normalize(expected) == _normalize(actual)


def _actual_value(invoice: Invoice, field: str):
    value = getattr(invoice, field)
    return value.value if hasattr(value, "value") else value


def summarize(outcomes: list[DocOutcome]) -> dict:
    per_field = {field: [] for field in FIELDS}
    true_positives = predicted = expected_total = 0
    for o in outcomes:
        expected_invoice = o.expected["invoice"]
        if expected_invoice is not None:
            for field in FIELDS:
                actual = _actual_value(o.invoice, field) if o.invoice else None
                per_field[field].append(o.invoice is not None and field_matches(field, expected_invoice[field], actual))
        expected_codes = set(o.expected["expected_issues"])
        true_positives += len(expected_codes & o.issues)
        predicted += len(o.issues)
        expected_total += len(expected_codes)

    scored = [ok for values in per_field.values() for ok in values]
    costs = [o.cost_usd for o in outcomes if o.cost_usd is not None]
    return {
        "documents": len(outcomes),
        "field_accuracy": {f: (sum(v) / len(v) if v else 0.0) for f, v in per_field.items()},
        "overall_field_accuracy": sum(scored) / len(scored) if scored else 0.0,
        "detection_precision": true_positives / predicted if predicted else 1.0,
        "detection_recall": true_positives / expected_total if expected_total else 1.0,
        "verdict_accuracy": mean(o.status == o.expected["expected_status"] for o in outcomes) if outcomes else 0.0,
        "mean_cost_usd": mean(costs) if costs else None,
        "mean_seconds": mean(o.seconds for o in outcomes) if outcomes else 0.0,
    }


def _pct(value: float) -> str:
    return f"{value * 100:.1f} %".replace(".", ",")


def to_markdown(model: str, summary: dict) -> str:
    cost = f"{summary['mean_cost_usd']:.4f} $" if summary["mean_cost_usd"] is not None else "n/d"
    lines = [
        f"## Résultats — `{model}` ({summary['documents']} documents)",
        "",
        "| Métrique | Valeur |",
        "|---|---|",
        f"| Précision des champs (globale) | {_pct(summary['overall_field_accuracy'])} |",
        f"| Détection d'anomalies — précision | {_pct(summary['detection_precision'])} |",
        f"| Détection d'anomalies — rappel | {_pct(summary['detection_recall'])} |",
        f"| Verdicts corrects | {_pct(summary['verdict_accuracy'])} |",
        f"| Coût moyen par document | {cost} |",
        f"| Temps moyen par document | {summary['mean_seconds']:.1f} s |",
        "",
        "| Champ | Précision |",
        "|---|---|",
    ]
    lines += [f"| `{field}` | {_pct(acc)} |" for field, acc in summary["field_accuracy"].items()]
    return "\n".join(lines) + "\n"
