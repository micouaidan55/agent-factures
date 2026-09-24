"""Boucle agentique : Claude demande des outils, le code les exécute, jusqu'au verdict."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import anthropic

from agent_factures.agent.documents import DocumentError, load_document
from agent_factures.agent.executor import ToolCall, ToolExecutor
from agent_factures.agent.tool_defs import TOOLS
from agent_factures.extraction.models import Invoice, Issue, Status, Verdict
from agent_factures.storage.repository import InvoiceRepository

MODELS = ["claude-sonnet-5", "claude-haiku-4-5"]
DEFAULT_MODEL = "claude-sonnet-5"
PRICES_PER_MTOK = {"claude-sonnet-5": (2.00, 10.00), "claude-haiku-4-5": (1.00, 5.00)}
MAX_TOKENS = 16000
DEFAULT_COMPANY = "Atelier Lumière SAS"

SYSTEM_PROMPT_TEMPLATE = """Tu es l'assistant comptable de l'entreprise « {company} », une PME française. Tu traites un seul document à la fois.

1. Si le document n'est ni une facture ni un devis, appelle directement submit_verdict avec le statut "a_revoir" en expliquant ce que c'est.
2. Sinon, extrais ses données et appelle submit_extraction. Montants en nombres, dates au format AAAA-MM-JJ. N'invente aucune valeur : si l'échéance n'apparaît pas, mets null. Le sens est « emise » si {company} est l'émetteur du document, « recue » si c'est un fournisseur qui l'a émis.
3. Si submit_extraction renvoie une erreur, corrige l'extraction et renvoie-la.
4. Lance ensuite les vérifications utiles (check_amounts, check_due_date, find_duplicates, get_supplier_history). Tu peux les appeler en parallèle.
5. Termine par submit_verdict : "ok" si aucun problème, "anomalie" si au moins un problème a été détecté, "a_revoir" si le document est illisible ou ambigu. L'explication s'adresse à un gestionnaire non technique, en 1 à 3 phrases."""

USER_INSTRUCTION = "Traite ce document."

CHECK_TOOLS = ("check_amounts", "check_due_date", "find_duplicates", "get_supplier_history")


@dataclass
class AgentResult:
    invoice: Invoice | None
    partial_extraction: dict | None
    verdict: Verdict
    issues: list[Issue]
    trace: list[ToolCall]
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class InvoiceAgent:
    def __init__(
        self,
        client,
        repo: InvoiceRepository,
        model: str = DEFAULT_MODEL,
        today: date | None = None,
        max_iterations: int = 10,
        company: str = DEFAULT_COMPANY,
    ):
        self.client = client
        self.repo = repo
        self.model = model
        self.today = today or date.today()
        self.max_iterations = max_iterations
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(company=company)

    def process(self, path: Path) -> AgentResult:
        executor = ToolExecutor(self.repo, self.today)
        tokens = [0, 0]
        try:
            document = load_document(path)
        except DocumentError as exc:
            return self._result(executor, tokens, fallback=str(exc))

        messages = [{"role": "user", "content": [document, {"type": "text", "text": USER_INSTRUCTION}]}]
        for _ in range(self.max_iterations):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    system=self.system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
            except anthropic.APIError as exc:
                return self._result(executor, tokens, fallback=f"Erreur d'API Claude ({type(exc).__name__}) : {exc}")
            tokens[0] += response.usage.input_tokens
            tokens[1] += response.usage.output_tokens

            if response.stop_reason != "tool_use":
                fallback = f"L'agent s'est arrêté sans rendre de verdict (stop_reason : {response.stop_reason})."
                return self._result(executor, tokens, fallback=fallback)

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output, is_error = executor.execute(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
            messages.append({"role": "user", "content": results})

            if executor.verdict is not None:
                return self._result(executor, tokens)

        return self._result(executor, tokens, fallback=f"Limite de {self.max_iterations} itérations atteinte.")

    def _ensure_checks_run(self, executor: ToolExecutor) -> None:
        """Force l'exécution des contrôles déterministes que Claude aurait pu sauter,
        pour ne jamais perdre silencieusement une anomalie (doublon, montant inhabituel...)."""
        last_extraction = -1
        for i, call in enumerate(executor.trace):
            if call.name == "submit_extraction" and not call.is_error:
                last_extraction = i
        already_run = {
            call.name
            for call in executor.trace[last_extraction + 1 :]
            if call.name in CHECK_TOOLS and not call.is_error
        }
        for name in CHECK_TOOLS:
            if name not in already_run:
                executor.execute(name, {})

    def _result(self, executor: ToolExecutor, tokens: list[int], fallback: str | None = None) -> AgentResult:
        if executor.invoice is not None:
            self._ensure_checks_run(executor)
        verdict = executor.verdict or Verdict(status=Status.NEEDS_REVIEW, explanation=fallback or "Aucun verdict.")
        if verdict.status is Status.OK and executor.issues:
            codes = ", ".join(issue.code for issue in executor.issues)
            verdict = Verdict(
                status=Status.ANOMALY,
                explanation=f"{verdict.explanation} (Requalifié en anomalie par les contrôles : {codes}.)",
            )
        prices = PRICES_PER_MTOK.get(self.model)
        cost = (tokens[0] * prices[0] + tokens[1] * prices[1]) / 1_000_000 if prices else None
        return AgentResult(
            invoice=executor.invoice,
            partial_extraction=executor.partial_extraction,
            verdict=verdict,
            issues=list(executor.issues),
            trace=list(executor.trace),
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            cost_usd=cost,
        )
