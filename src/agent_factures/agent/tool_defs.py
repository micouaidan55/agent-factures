"""Définition des outils exposés à Claude. Aucun n'écrit en base."""

from agent_factures.extraction.models import Direction, DocumentType, Status

NO_INPUT = {"type": "object", "properties": {}}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": [t.value for t in DocumentType], "description": "Nature du document."},
        "direction": {
            "type": "string",
            "enum": [d.value for d in Direction],
            "description": "« emise » si l'entreprise utilisatrice est l'émettrice du document, « recue » sinon.",
        },
        "supplier": {"type": "string", "description": "Raison sociale de l'émetteur du document."},
        "customer": {
            "type": ["string", "null"],
            "description": "Raison sociale du destinataire du document, ou null si absente.",
        },
        "number": {"type": "string", "description": "Numéro de facture ou de devis, tel qu'imprimé."},
        "issue_date": {"type": "string", "description": "Date d'émission au format AAAA-MM-JJ."},
        "due_date": {
            "type": ["string", "null"],
            "description": "Date d'échéance au format AAAA-MM-JJ, ou null si absente du document.",
        },
        "amount_excl_tax": {"type": "number", "description": "Total hors taxes."},
        "vat_amount": {"type": "number", "description": "Montant total de la TVA."},
        "amount_incl_tax": {"type": "number", "description": "Total toutes taxes comprises."},
        "currency": {"type": "string", "description": "Code ISO 4217 (EUR par défaut)."},
        "lines": {
            "type": "array",
            "description": "Lignes de détail, dans l'ordre du document.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number", "description": "Prix unitaire HT."},
                    "total": {"type": "number", "description": "Total HT de la ligne."},
                },
                "required": ["description", "quantity", "unit_price", "total"],
            },
        },
    },
    "required": [
        "doc_type", "direction", "supplier", "number", "issue_date", "amount_excl_tax", "vat_amount", "amount_incl_tax",
    ],
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": [s.value for s in Status]},
        "explanation": {
            "type": "string",
            "description": "1 à 3 phrases en français pour un gestionnaire non technique.",
        },
    },
    "required": ["status", "explanation"],
}

TOOLS = [
    {
        "name": "submit_extraction",
        "description": "Enregistre les données extraites du document. À appeler une fois l'extraction terminée.",
        "input_schema": INVOICE_SCHEMA,
    },
    {
        "name": "check_amounts",
        "description": "Vérifie que HT + TVA = TTC et que la somme des lignes égale le HT, sur la dernière extraction.",
        "input_schema": NO_INPUT,
    },
    {
        "name": "check_due_date",
        "description": "Indique si l'échéance de la facture extraite est dépassée à la date du jour.",
        "input_schema": NO_INPUT,
    },
    {
        "name": "find_duplicates",
        "description": "Cherche une pièce déjà enregistrée avec le même fournisseur et le même numéro.",
        "input_schema": NO_INPUT,
    },
    {
        "name": "get_supplier_history",
        "description": "Renvoie l'historique du fournisseur et signale un montant inhabituel.",
        "input_schema": NO_INPUT,
    },
    {
        "name": "submit_verdict",
        "description": "Rend le verdict final sur le document. Termine le traitement.",
        "input_schema": VERDICT_SCHEMA,
    },
]

TOOL_NAMES = {tool["name"] for tool in TOOLS}
