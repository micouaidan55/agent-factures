"""Modèles de données d'un document comptable (facture ou devis)."""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    INVOICE = "facture"
    QUOTE = "devis"


class Direction(StrEnum):
    RECEIVED = "recue"
    ISSUED = "emise"


class Status(StrEnum):
    OK = "ok"
    ANOMALY = "anomalie"
    NEEDS_REVIEW = "a_revoir"


class InvoiceLine(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


class Invoice(BaseModel):
    doc_type: DocumentType
    direction: Direction
    supplier: str = Field(min_length=1)
    customer: str | None = None
    number: str = Field(min_length=1)
    issue_date: date
    due_date: date | None = None
    amount_excl_tax: Decimal
    vat_amount: Decimal
    amount_incl_tax: Decimal
    currency: str = "EUR"
    lines: list[InvoiceLine] = Field(default_factory=list)


class Issue(BaseModel):
    code: str
    message: str


class Verdict(BaseModel):
    status: Status
    explanation: str = Field(min_length=1)
