"""Vérifications déterministes d'un document, sans accès à la base."""

from datetime import date
from decimal import Decimal

from agent_factures.extraction.models import Direction, DocumentType, Invoice, Issue

TOLERANCE = Decimal("0.02")


def check_amounts(invoice: Invoice) -> list[Issue]:
    issues = []
    computed = invoice.amount_excl_tax + invoice.vat_amount
    if abs(computed - invoice.amount_incl_tax) > TOLERANCE:
        issues.append(
            Issue(
                code="TOTAL_INCOHERENT",
                message=f"HT + TVA = {computed} mais le TTC indiqué est {invoice.amount_incl_tax}.",
            )
        )
    if invoice.lines:
        lines_total = sum((line.total for line in invoice.lines), Decimal("0"))
        if abs(lines_total - invoice.amount_excl_tax) > TOLERANCE:
            issues.append(
                Issue(
                    code="LIGNES_INCOHERENTES",
                    message=f"La somme des lignes ({lines_total}) ne correspond pas au HT ({invoice.amount_excl_tax}).",
                )
            )
    return issues


def check_due_date(invoice: Invoice, today: date) -> Issue | None:
    if invoice.doc_type is not DocumentType.INVOICE or invoice.due_date is None:
        return None
    days_late = (today - invoice.due_date).days
    if days_late <= 0:
        return None
    consequence = "impayé client, relance à prévoir" if invoice.direction is Direction.ISSUED else "facture à payer"
    return Issue(
        code="ECHEANCE_DEPASSEE",
        message=f"Échéance du {invoice.due_date:%d/%m/%Y} dépassée de {days_late} jours ({consequence}).",
    )
