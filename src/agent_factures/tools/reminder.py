"""Brouillons de mails (relance client, demande de facture rectificative). Rien n'est envoyé."""

from datetime import date

from agent_factures.extraction.models import Direction, Invoice, Issue
from agent_factures.tools.formatting import euros

AMOUNT_ERROR_CODES = {"TOTAL_INCOHERENT", "LIGNES_INCOHERENTES"}


def draft_reminder(invoice: Invoice, today: date) -> str:
    if invoice.direction is not Direction.ISSUED:
        raise ValueError("Une relance ne concerne qu'une facture émise vers un client.")
    due = invoice.due_date or today
    days_late = max((today - due).days, 0)
    return (
        f"À : {invoice.customer or 'client'}\n"
        f"Objet : facture n° {invoice.number} — échéance dépassée\n\n"
        f"Bonjour,\n\n"
        f"Sauf erreur de notre part, notre facture n° {invoice.number} d'un montant de "
        f"{euros(invoice.amount_incl_tax)} TTC est arrivée à échéance le {due:%d/%m/%Y}, "
        f"soit un retard de {days_late} jours.\n\n"
        f"Pourriez-vous nous indiquer la date de règlement prévue ? Si le paiement a été effectué entre-temps, "
        f"merci de ne pas tenir compte de ce message.\n\n"
        f"Cordialement,\n{invoice.supplier}"
    )


def draft_correction_request(invoice: Invoice, issues: list[Issue]) -> str:
    """Demande de facture rectificative au fournisseur, pour une facture reçue rejetée pour erreur de montant."""
    if invoice.direction is not Direction.RECEIVED:
        raise ValueError("Une demande de rectification ne concerne qu'une facture reçue d'un fournisseur.")
    errors = [issue for issue in issues if issue.code in AMOUNT_ERROR_CODES]
    if not errors:
        raise ValueError("Aucune erreur de montant à signaler.")
    details = "\n".join(f"- {issue.message}" for issue in errors)
    return (
        f"À : {invoice.supplier}\n"
        f"Objet : facture n° {invoice.number} — demande de facture rectificative\n\n"
        f"Bonjour,\n\n"
        f"Nous avons bien reçu votre facture n° {invoice.number} du {invoice.issue_date:%d/%m/%Y}, "
        f"d'un montant de {euros(invoice.amount_incl_tax)} TTC. Lors de sa vérification, nous avons relevé "
        f"les incohérences suivantes :\n{details}\n\n"
        f"Nous ne pouvons pas l'enregistrer en l'état. Pourriez-vous nous adresser une facture rectificative ?\n\n"
        f"Cordialement,\n{invoice.customer or ''}"
    ).rstrip()
