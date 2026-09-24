"""Formatage partagé des montants pour les messages destinés à l'utilisateur."""

from decimal import Decimal


def euros(amount: Decimal) -> str:
    return f"{amount:,.2f} €".replace(",", " ").replace(".", ",")
