"""Brouillon de relance d'un client pour une facture émise impayée. Rien n'est envoyé."""

from datetime import date

from agent_factures.extraction.models import Direction, Invoice
from agent_factures.tools.formatting import euros


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
