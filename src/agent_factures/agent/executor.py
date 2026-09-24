"""Exécute les outils demandés par Claude et garde l'état du traitement d'un document."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from agent_factures.extraction.models import Invoice, Issue, Status, Verdict
from agent_factures.storage.repository import InvoiceRepository
from agent_factures.tools.checks import check_amounts, check_due_date
from agent_factures.tools.history import check_unusual_amount, find_duplicates, get_supplier_history

ToolOutput = tuple[str, bool]


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str
    is_error: bool


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class ToolExecutor:
    MAX_EXTRACTION_ATTEMPTS = 2

    def __init__(self, repo: InvoiceRepository, today: date):
        self.repo = repo
        self.today = today
        self.invoice: Invoice | None = None
        self.partial_extraction: dict | None = None
        self.verdict: Verdict | None = None
        self.issues: list[Issue] = []
        self.trace: list[ToolCall] = []
        self._extraction_failures = 0
        self._handlers: dict[str, Callable[[dict], ToolOutput]] = {
            "submit_extraction": self._submit_extraction,
            "check_amounts": self._check_amounts,
            "check_due_date": self._check_due_date,
            "find_duplicates": self._find_duplicates,
            "get_supplier_history": self._get_supplier_history,
            "submit_verdict": self._submit_verdict,
        }

    def execute(self, name: str, tool_input: dict) -> ToolOutput:
        handler = self._handlers.get(name)
        if handler:
            try:
                output, is_error = handler(tool_input)
            except Exception as exc:
                output, is_error = f"Erreur interne de l'outil {name} : {exc}", True
        else:
            output, is_error = f"Outil inconnu : {name}.", True
        self.trace.append(ToolCall(name=name, input=tool_input, output=output, is_error=is_error))
        return output, is_error

    def _add_issues(self, issues: list[Issue]) -> None:
        known = {issue.code for issue in self.issues}
        self.issues.extend(issue for issue in issues if issue.code not in known)

    def _missing_extraction(self) -> ToolOutput:
        return "Aucune extraction valide : appelle d'abord submit_extraction.", True

    def _submit_extraction(self, data: dict) -> ToolOutput:
        try:
            self.invoice = Invoice.model_validate(data)
        except ValidationError as exc:
            self._extraction_failures += 1
            self.partial_extraction = data
            if self._extraction_failures >= self.MAX_EXTRACTION_ATTEMPTS:
                self.verdict = Verdict(
                    status=Status.NEEDS_REVIEW,
                    explanation=f"Extraction invalide après {self.MAX_EXTRACTION_ATTEMPTS} tentatives : saisie manuelle nécessaire.",
                )
                return f"Extraction toujours invalide, document marqué à revoir : {exc}", True
            return f"Extraction invalide, corrige et renvoie-la : {exc}", True
        self.partial_extraction = None
        return "Extraction enregistrée.", False

    def _check_amounts(self, _: dict) -> ToolOutput:
        if self.invoice is None:
            return self._missing_extraction()
        issues = check_amounts(self.invoice)
        self._add_issues(issues)
        return _json([issue.model_dump() for issue in issues]), False

    def _check_due_date(self, _: dict) -> ToolOutput:
        if self.invoice is None:
            return self._missing_extraction()
        issue = check_due_date(self.invoice, self.today)
        if issue is None:
            return _json({"code": None, "message": "Échéance non dépassée ou non applicable."}), False
        self._add_issues([issue])
        return _json(issue.model_dump()), False

    def _find_duplicates(self, _: dict) -> ToolOutput:
        if self.invoice is None:
            return self._missing_extraction()
        duplicates = find_duplicates(self.repo, self.invoice.supplier, self.invoice.number)
        if duplicates:
            self._add_issues(
                [Issue(code="DOUBLON", message=f"Pièce déjà enregistrée ({len(duplicates)} occurrence(s)).")]
            )
        return _json({"doublons": [{"id": d.id, "fichier": d.source_file} for d in duplicates]}), False

    def _get_supplier_history(self, _: dict) -> ToolOutput:
        if self.invoice is None:
            return self._missing_extraction()
        stats = get_supplier_history(self.repo, self.invoice.supplier)
        issue = check_unusual_amount(self.invoice, stats)
        if issue:
            self._add_issues([issue])
        return _json(
            {
                "nombre_factures": stats.count,
                "moyenne_ttc": stats.average_incl_tax,
                "alerte": issue.model_dump() if issue else None,
            }
        ), False

    def _submit_verdict(self, data: dict) -> ToolOutput:
        try:
            self.verdict = Verdict.model_validate(data)
        except ValidationError as exc:
            return f"Verdict invalide : {exc}", True
        return "Verdict enregistré.", False
