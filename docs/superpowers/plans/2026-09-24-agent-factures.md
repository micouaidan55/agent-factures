# Agent de factures — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** construire un agent Claude qui lit des factures et devis (PDF ou image), extrait et vérifie leurs données, les soumet à validation humaine dans une interface Streamlit, et mesure sa propre précision avec un jeu d'évaluation.

**Architecture :** un package Python `agent_factures` (layout `src/`) découpé en `extraction` (modèles Pydantic), `storage` (SQLite et exports), `tools` (vérifications pures) et `agent` (chargement des documents, exécuteur d'outils, boucle agentique manuelle sur l'API Messages). L'interface `app/main.py` orchestre le tout et est la seule à écrire en base, après validation humaine. `evals/` génère un jeu de documents fictifs et en mesure les résultats.

**Tech Stack :** Python 3.12, uv, anthropic (SDK officiel), pydantic v2, sqlite3 (stdlib), streamlit, pandas et openpyxl, python-dotenv, reportlab et pillow (génération des evals), pytest.

**Spec :** `docs/superpowers/specs/2026-09-24-agent-factures-design.md`

## Global Constraints

- Python >= 3.12, dépendances gérées avec `uv` (`uv add`, `uv run`).
- Modèles : `claude-sonnet-5` par défaut, `claude-haiku-4-5` en option. Utiliser exactement ces identifiants, sans suffixe de date.
- Prix (USD par million de tokens, entrée/sortie) : Sonnet 5 = 2,00 / 10,00 ; Haiku 4.5 = 1,00 / 5,00.
- Ne pas passer de paramètre `thinking` (Sonnet 5 fonctionne alors en thinking adaptatif, Haiku 4.5 sans thinking). Toujours renvoyer `response.content` complet dans l'historique.
- `max_tokens=16000` par requête (non streamée).
- Nombre maximal d'itérations de la boucle : 10 par document.
- Tolérance de cohérence des montants : 0,02 €. Tolérance de comparaison dans les evals : 0,01.
- Montant inhabituel : TTC strictement supérieur à 3 fois la moyenne TTC des factures du même fournisseur, uniquement si au moins 3 factures d'historique.
- L'agent n'écrit **jamais** en base : seuls des outils en lecture seule lui sont exposés. L'écriture se fait dans `app/main.py` après clic sur « Accepter ».
- Aucun test ne doit appeler l'API réelle (client factice injecté).
- Textes visibles par l'utilisateur en français.
- Sens des factures (spec §12) : `direction` = `recue` (fournisseur → entreprise) ou `emise` (entreprise → client). Nom de l'entreprise : variable d'environnement `COMPANY_NAME`, défaut `Atelier Lumière SAS`. Les relances ne concernent que les factures émises ; le montant inhabituel ne concerne que les factures reçues.
- Clé d'API lue depuis `ANTHROPIC_API_KEY` (fichier `.env` ignoré par git).
- Chaque message de commit se termine par la ligne `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Écart assumé par rapport à la spec §4 : les modules vivent dans `src/agent_factures/` (package installable) au lieu de dossiers à la racine, pour que `app/`, `evals/` et `tests/` importent le même code sans bidouille de `sys.path`.

## Structure des fichiers

```
agent-factures/
├── pyproject.toml
├── .env.example
├── README.md
├── src/agent_factures/
│   ├── __init__.py
│   ├── extraction/__init__.py, models.py      # Invoice, InvoiceLine, Issue, Verdict, enums
│   ├── storage/__init__.py
│   │   ├── db.py                              # connect(), supplier_key()
│   │   ├── repository.py                      # InvoiceRepository, StoredInvoice
│   │   ├── action_log.py                      # ActionLog, LogEntry
│   │   └── export.py                          # to_rows, to_csv_bytes, to_excel_bytes
│   ├── tools/__init__.py
│   │   ├── checks.py                          # check_amounts, check_due_date
│   │   ├── history.py                         # find_duplicates, get_supplier_history, check_unusual_amount
│   │   └── reminder.py                        # draft_reminder
│   └── agent/__init__.py
│       ├── documents.py                       # load_document, DocumentError
│       ├── tool_defs.py                       # TOOLS (schémas envoyés à Claude)
│       ├── executor.py                        # ToolExecutor, ToolCall
│       └── loop.py                            # InvoiceAgent, AgentResult, MODELS, prompts
├── app/main.py                                # Interface Streamlit
├── evals/__init__.py, generate.py, scoring.py, run.py, dataset/, results/
├── inbox/.gitkeep
└── tests/__init__.py, factories.py, fakes.py, test_*.py
```

---

### Task 0 : prérequis machine (action de l'utilisateur)

`uv` n'est pas installé et le Python système est en 3.9. L'utilisateur installe uv lui-même :

- [ ] **Step 1 : installer uv**

```bash
brew install uv
```

- [ ] **Step 2 : vérifier**

Run : `uv --version`
Expected : `uv 0.x.y` (uv téléchargera Python 3.12 automatiquement à la Task 1).

---

### Task 1 : squelette du projet et modèles de données

**Files :**
- Create : `pyproject.toml`, `.env.example`, `inbox/.gitkeep`, `src/agent_factures/__init__.py`, `src/agent_factures/extraction/__init__.py`, `src/agent_factures/extraction/models.py`
- Test : `tests/__init__.py`, `tests/factories.py`, `tests/test_models.py`

**Interfaces :**
- Produces :
  - `DocumentType(StrEnum)` : `INVOICE = "facture"`, `QUOTE = "devis"`
  - `Direction(StrEnum)` : `RECEIVED = "recue"`, `ISSUED = "emise"`
  - `Status(StrEnum)` : `OK = "ok"`, `ANOMALY = "anomalie"`, `NEEDS_REVIEW = "a_revoir"`
  - `InvoiceLine(description: str, quantity: Decimal, unit_price: Decimal, total: Decimal)`
  - `Invoice(doc_type, direction: Direction, supplier, customer: str | None = None, number, issue_date: date, due_date: date | None, amount_excl_tax, vat_amount, amount_incl_tax: Decimal, currency: str = "EUR", lines: list[InvoiceLine])` — `supplier` = émetteur du document, `customer` = destinataire
  - `Issue(code: str, message: str)`
  - `Verdict(status: Status, explanation: str)`
  - `tests.factories.make_invoice(**overrides) -> Invoice`

- [ ] **Step 1 : initialiser le projet**

```bash
cd ~/projets/agent-factures
uv python install 3.12
```

Créer `pyproject.toml` :

```toml
[project]
name = "agent-factures"
version = "0.1.0"
description = "Agent IA de traitement de factures et devis pour PME"
requires-python = ">=3.12"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agent_factures"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Puis :

```bash
uv add anthropic "pydantic>=2" streamlit pandas openpyxl python-dotenv reportlab pillow
uv add --dev pytest
mkdir -p src/agent_factures/extraction tests inbox
touch src/agent_factures/__init__.py src/agent_factures/extraction/__init__.py tests/__init__.py inbox/.gitkeep
printf 'ANTHROPIC_API_KEY=\nCOMPANY_NAME=Atelier Lumière SAS\n' > .env.example
printf 'data/\n' >> .gitignore
```

- [ ] **Step 2 : écrire les tests qui échouent**

`tests/factories.py` :

```python
from datetime import date
from decimal import Decimal

from agent_factures.extraction.models import Invoice


def make_invoice(**overrides) -> Invoice:
    data = {
        "doc_type": "facture",
        "direction": "recue",
        "supplier": "Bureau Plus SARL",
        "customer": "Atelier Lumière SAS",
        "number": "F-001",
        "issue_date": date(2026, 9, 1),
        "due_date": date(2026, 10, 1),
        "amount_excl_tax": Decimal("100.00"),
        "vat_amount": Decimal("20.00"),
        "amount_incl_tax": Decimal("120.00"),
        "lines": [
            {"description": "Ramettes de papier", "quantity": "10", "unit_price": "10.00", "total": "100.00"}
        ],
    }
    data.update(overrides)
    return Invoice.model_validate(data)
```

`tests/test_models.py` :

```python
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_factures.extraction.models import Direction, DocumentType, Invoice, Status, Verdict
from tests.factories import make_invoice


def test_invoice_parses_claude_style_payload():
    invoice = Invoice.model_validate(
        {
            "doc_type": "facture",
            "direction": "emise",
            "supplier": "Bureau Plus SARL",
            "number": "F-2026-101",
            "issue_date": "2026-09-01",
            "due_date": None,
            "amount_excl_tax": 100.1,
            "vat_amount": 20.02,
            "amount_incl_tax": 120.12,
        }
    )
    assert invoice.doc_type is DocumentType.INVOICE
    assert invoice.direction is Direction.ISSUED
    assert invoice.customer is None
    assert invoice.issue_date == date(2026, 9, 1)
    assert invoice.due_date is None
    assert invoice.amount_excl_tax == Decimal("100.1")
    assert invoice.currency == "EUR"
    assert invoice.lines == []


def test_invoice_rejects_empty_supplier():
    with pytest.raises(ValidationError):
        make_invoice(supplier="")


def test_invoice_rejects_unknown_doc_type():
    with pytest.raises(ValidationError):
        make_invoice(doc_type="bon de commande")


def test_invoice_requires_a_known_direction():
    with pytest.raises(ValidationError):
        make_invoice(direction="sortante")
    with pytest.raises(ValidationError):
        make_invoice(direction=None)


def test_verdict_accepts_known_status_and_rejects_others():
    assert Verdict(status="anomalie", explanation="TVA incohérente").status is Status.ANOMALY
    with pytest.raises(ValidationError):
        Verdict(status="parfait", explanation="?")
    with pytest.raises(ValidationError):
        Verdict(status="ok", explanation="")
```

- [ ] **Step 3 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_models.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.extraction.models'`

- [ ] **Step 4 : implémenter**

`src/agent_factures/extraction/models.py` :

```python
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
```

- [ ] **Step 5 : vérifier que les tests passent**

Run : `uv run pytest tests/test_models.py -v`
Expected : 5 passed

- [ ] **Step 6 : commit**

```bash
git add -A
git commit -m "feat: squelette du projet et modèles de données" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2 : stockage SQLite (factures et journal)

**Files :**
- Create : `src/agent_factures/storage/__init__.py`, `src/agent_factures/storage/db.py`, `src/agent_factures/storage/repository.py`, `src/agent_factures/storage/action_log.py`
- Test : `tests/test_storage.py`

**Interfaces :**
- Consumes : `Invoice`, `DocumentType` (Task 1), `make_invoice`
- Produces :
  - `connect(path: str = ":memory:") -> sqlite3.Connection`
  - `supplier_key(name: str) -> str` (minuscules, espaces normalisés)
  - `StoredInvoice(id: int, invoice: Invoice, source_file: str)`
  - `InvoiceRepository(conn)` : `add(invoice, source_file) -> int`, `get(invoice_id) -> StoredInvoice | None`, `find_by_supplier_and_number(supplier, number) -> list[StoredInvoice]`, `list_by_supplier(supplier) -> list[StoredInvoice]`, `list_overdue(today: date, direction: Direction | None = None) -> list[StoredInvoice]`, `list_all() -> list[StoredInvoice]`
  - `LogEntry(document: str, action: str, detail: dict, created_at: str)`
  - `ActionLog(conn)` : `record(document, action, detail: dict | None = None) -> None`, `list_for_document(document) -> list[LogEntry]`, `list_recent(limit: int = 50) -> list[LogEntry]`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_storage.py` :

```python
from datetime import date

from agent_factures.storage.action_log import ActionLog
from agent_factures.storage.db import connect, supplier_key
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice


def make_repo() -> InvoiceRepository:
    return InvoiceRepository(connect())


def test_supplier_key_normalizes_case_and_spaces():
    assert supplier_key("  Bureau   PLUS sarl ") == "bureau plus sarl"


def test_add_then_get_roundtrip():
    repo = make_repo()
    invoice = make_invoice()
    invoice_id = repo.add(invoice, source_file="inbox/f1.pdf")
    stored = repo.get(invoice_id)
    assert stored is not None
    assert stored.invoice == invoice
    assert stored.source_file == "inbox/f1.pdf"
    assert repo.get(9999) is None


def test_find_by_supplier_and_number_ignores_supplier_case():
    repo = make_repo()
    repo.add(make_invoice(supplier="Bureau Plus SARL", number="F-001"), "a.pdf")
    repo.add(make_invoice(supplier="Bureau Plus SARL", number="F-002"), "b.pdf")
    found = repo.find_by_supplier_and_number("bureau plus sarl", "F-001")
    assert [s.source_file for s in found] == ["a.pdf"]


def test_list_by_supplier():
    repo = make_repo()
    repo.add(make_invoice(supplier="A", number="1"), "a.pdf")
    repo.add(make_invoice(supplier="B", number="2"), "b.pdf")
    repo.add(make_invoice(supplier="a", number="3"), "c.pdf")
    assert [s.invoice.number for s in repo.list_by_supplier("A")] == ["1", "3"]


def test_list_overdue_only_returns_invoices_past_due():
    repo = make_repo()
    repo.add(make_invoice(number="late", due_date=date(2026, 9, 1)), "late.pdf")
    repo.add(make_invoice(number="future", due_date=date(2026, 12, 1)), "future.pdf")
    repo.add(make_invoice(number="nodue", due_date=None), "nodue.pdf")
    repo.add(make_invoice(number="quote", doc_type="devis", due_date=date(2026, 9, 1)), "quote.pdf")
    overdue = repo.list_overdue(date(2026, 9, 24))
    assert [s.invoice.number for s in overdue] == ["late"]


def test_list_overdue_can_filter_by_direction():
    repo = make_repo()
    repo.add(make_invoice(number="to-pay", due_date=date(2026, 9, 1)), "a.pdf")
    repo.add(make_invoice(number="to-collect", direction="emise", due_date=date(2026, 9, 2)), "b.pdf")
    today = date(2026, 9, 24)
    assert [s.invoice.number for s in repo.list_overdue(today, direction="recue")] == ["to-pay"]
    assert [s.invoice.number for s in repo.list_overdue(today, direction="emise")] == ["to-collect"]
    assert len(repo.list_overdue(today)) == 2


def test_list_all_in_insertion_order():
    repo = make_repo()
    repo.add(make_invoice(number="1"), "1.pdf")
    repo.add(make_invoice(number="2"), "2.pdf")
    assert [s.invoice.number for s in repo.list_all()] == ["1", "2"]


def test_action_log_records_and_lists():
    log = ActionLog(connect())
    log.record("f1.pdf", "analyse", {"statut": "ok", "cout_usd": 0.01})
    log.record("f2.pdf", "analyse")
    log.record("f1.pdf", "accepte", {"id": 1})
    entries = log.list_for_document("f1.pdf")
    assert [e.action for e in entries] == ["analyse", "accepte"]
    assert entries[0].detail == {"statut": "ok", "cout_usd": 0.01}
    assert [e.document for e in log.list_recent(limit=2)] == ["f1.pdf", "f2.pdf"]
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_storage.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.storage'`

- [ ] **Step 3 : implémenter**

```bash
mkdir -p src/agent_factures/storage && touch src/agent_factures/storage/__init__.py
```

`src/agent_factures/storage/db.py` :

```python
"""Connexion SQLite et création du schéma."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_key TEXT NOT NULL,
    number TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    due_date TEXT,
    amount_incl_tax TEXT NOT NULL,
    data TEXT NOT NULL,
    source_file TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices (supplier_key, number);
CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def supplier_key(name: str) -> str:
    return " ".join(name.casefold().split())
```

`src/agent_factures/storage/repository.py` :

```python
"""Accès aux factures enregistrées."""

import sqlite3
from datetime import date

from pydantic import BaseModel

from agent_factures.extraction.models import Direction, DocumentType, Invoice
from agent_factures.storage.db import supplier_key


class StoredInvoice(BaseModel):
    id: int
    invoice: Invoice
    source_file: str


class InvoiceRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, invoice: Invoice, source_file: str) -> int:
        cursor = self._conn.execute(
            "INSERT INTO invoices (supplier_key, number, doc_type, direction, due_date, amount_incl_tax, data, source_file)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                supplier_key(invoice.supplier),
                invoice.number.strip(),
                invoice.doc_type.value,
                invoice.direction.value,
                invoice.due_date.isoformat() if invoice.due_date else None,
                str(invoice.amount_incl_tax),
                invoice.model_dump_json(),
                source_file,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get(self, invoice_id: int) -> StoredInvoice | None:
        rows = self._select("WHERE id = ?", (invoice_id,))
        return rows[0] if rows else None

    def find_by_supplier_and_number(self, supplier: str, number: str) -> list[StoredInvoice]:
        return self._select("WHERE supplier_key = ? AND number = ?", (supplier_key(supplier), number.strip()))

    def list_by_supplier(self, supplier: str) -> list[StoredInvoice]:
        return self._select("WHERE supplier_key = ?", (supplier_key(supplier),))

    def list_overdue(self, today: date, direction: Direction | None = None) -> list[StoredInvoice]:
        where = "WHERE doc_type = ? AND due_date IS NOT NULL AND due_date < ?"
        params: tuple = (DocumentType.INVOICE.value, today.isoformat())
        if direction is not None:
            where += " AND direction = ?"
            params += (Direction(direction).value,)
        return self._select(where, params, order="due_date, id")

    def list_all(self) -> list[StoredInvoice]:
        return self._select("", ())

    def _select(self, where: str, params: tuple, order: str = "id") -> list[StoredInvoice]:
        rows = self._conn.execute(f"SELECT id, data, source_file FROM invoices {where} ORDER BY {order}", params)
        return [
            StoredInvoice(id=row["id"], invoice=Invoice.model_validate_json(row["data"]), source_file=row["source_file"])
            for row in rows
        ]
```

`src/agent_factures/storage/action_log.py` :

```python
"""Journal des actions de l'agent et de l'utilisateur."""

import json
import sqlite3

from pydantic import BaseModel


class LogEntry(BaseModel):
    document: str
    action: str
    detail: dict
    created_at: str


class ActionLog:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def record(self, document: str, action: str, detail: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO action_log (document, action, detail) VALUES (?, ?, ?)",
            (document, action, json.dumps(detail or {}, ensure_ascii=False, default=str)),
        )
        self._conn.commit()

    def list_for_document(self, document: str) -> list[LogEntry]:
        return self._select("WHERE document = ? ORDER BY id", (document,))

    def list_recent(self, limit: int = 50) -> list[LogEntry]:
        return self._select("ORDER BY id DESC LIMIT ?", (limit,))

    def _select(self, clause: str, params: tuple) -> list[LogEntry]:
        rows = self._conn.execute(f"SELECT document, action, detail, created_at FROM action_log {clause}", params)
        return [
            LogEntry(document=r["document"], action=r["action"], detail=json.loads(r["detail"]), created_at=r["created_at"])
            for r in rows
        ]
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_storage.py -v`
Expected : 8 passed

- [ ] **Step 5 : commit**

```bash
git add -A
git commit -m "feat: stockage SQLite des factures et journal d'actions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3 : vérifications pures (montants, échéance) et brouillon de relance

**Files :**
- Create : `src/agent_factures/tools/__init__.py`, `src/agent_factures/tools/checks.py`, `src/agent_factures/tools/reminder.py`
- Test : `tests/test_checks.py`, `tests/test_reminder.py`

**Interfaces :**
- Consumes : `Invoice`, `Issue`, `DocumentType` (Task 1)
- Produces :
  - `TOLERANCE = Decimal("0.02")`
  - `check_amounts(invoice: Invoice) -> list[Issue]` (codes `TOTAL_INCOHERENT`, `LIGNES_INCOHERENTES`)
  - `check_due_date(invoice: Invoice, today: date) -> Issue | None` (code `ECHEANCE_DEPASSEE` ; message « à payer » si reçue, « impayé client » si émise)
  - `draft_reminder(invoice: Invoice, today: date) -> str` (lève `ValueError` si la facture n'est pas émise ; s'adresse à `customer`)

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_checks.py` :

```python
from datetime import date
from decimal import Decimal

from agent_factures.tools.checks import check_amounts, check_due_date
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)


def test_consistent_invoice_has_no_amount_issue():
    assert check_amounts(make_invoice()) == []


def test_rounding_within_tolerance_is_accepted():
    assert check_amounts(make_invoice(amount_incl_tax=Decimal("120.02"))) == []


def test_total_mismatch_is_flagged():
    issues = check_amounts(make_invoice(vat_amount=Decimal("25.00")))
    assert [i.code for i in issues] == ["TOTAL_INCOHERENT"]
    assert "125" in issues[0].message and "120" in issues[0].message


def test_lines_mismatch_is_flagged():
    invoice = make_invoice(
        amount_excl_tax=Decimal("150.00"), vat_amount=Decimal("30.00"), amount_incl_tax=Decimal("180.00")
    )
    assert [i.code for i in check_amounts(invoice)] == ["LIGNES_INCOHERENTES"]


def test_invoice_without_lines_skips_line_check():
    assert check_amounts(make_invoice(lines=[])) == []


def test_overdue_received_invoice_is_to_pay():
    issue = check_due_date(make_invoice(due_date=date(2026, 9, 10)), TODAY)
    assert issue is not None
    assert issue.code == "ECHEANCE_DEPASSEE"
    assert "14 jours" in issue.message
    assert "à payer" in issue.message


def test_overdue_issued_invoice_is_unpaid_by_customer():
    issue = check_due_date(make_invoice(direction="emise", due_date=date(2026, 9, 10)), TODAY)
    assert issue is not None
    assert issue.code == "ECHEANCE_DEPASSEE"
    assert "impayé client" in issue.message


def test_due_today_or_later_is_fine():
    assert check_due_date(make_invoice(due_date=TODAY), TODAY) is None


def test_quote_and_missing_due_date_are_ignored():
    assert check_due_date(make_invoice(doc_type="devis", due_date=date(2026, 1, 1)), TODAY) is None
    assert check_due_date(make_invoice(due_date=None), TODAY) is None
```

`tests/test_reminder.py` :

```python
from datetime import date

import pytest

from agent_factures.tools.reminder import draft_reminder
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)


def test_reminder_is_addressed_to_the_customer():
    invoice = make_invoice(
        direction="emise",
        supplier="Atelier Lumière SAS",
        customer="Hôtel Bellevue",
        number="AL-042",
        due_date=date(2026, 9, 10),
    )
    text = draft_reminder(invoice, TODAY)
    assert "AL-042" in text
    assert "Hôtel Bellevue" in text
    assert "120,00 €" in text
    assert "10/09/2026" in text
    assert "14 jours" in text
    assert "Atelier Lumière SAS" in text


def test_reminder_refuses_received_invoices():
    with pytest.raises(ValueError, match="émise"):
        draft_reminder(make_invoice(direction="recue"), TODAY)
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_checks.py tests/test_reminder.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.tools'`

- [ ] **Step 3 : implémenter**

```bash
mkdir -p src/agent_factures/tools && touch src/agent_factures/tools/__init__.py
```

`src/agent_factures/tools/checks.py` :

```python
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
```

`src/agent_factures/tools/reminder.py` :

```python
"""Brouillon de relance d'un client pour une facture émise impayée. Rien n'est envoyé."""

from datetime import date
from decimal import Decimal

from agent_factures.extraction.models import Direction, Invoice


def _euros(amount: Decimal) -> str:
    return f"{amount:,.2f} €".replace(",", " ").replace(".", ",")


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
        f"{_euros(invoice.amount_incl_tax)} TTC est arrivée à échéance le {due:%d/%m/%Y}, "
        f"soit un retard de {days_late} jours.\n\n"
        f"Pourriez-vous nous indiquer la date de règlement prévue ? Si le paiement a été effectué entre-temps, "
        f"merci de ne pas tenir compte de ce message.\n\n"
        f"Cordialement,\n{invoice.supplier}"
    )
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_checks.py tests/test_reminder.py -v`
Expected : 11 passed

- [ ] **Step 5 : commit**

```bash
git add -A
git commit -m "feat: vérifications des montants et échéances, brouillon de relance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4 : vérifications liées à l'historique (doublons, montant inhabituel)

**Files :**
- Create : `src/agent_factures/tools/history.py`
- Test : `tests/test_history.py`

**Interfaces :**
- Consumes : `InvoiceRepository`, `StoredInvoice`, `connect` (Task 2) ; `Invoice`, `Issue`, `DocumentType` (Task 1)
- Produces :
  - `find_duplicates(repo, supplier: str, number: str) -> list[StoredInvoice]`
  - `SupplierStats(supplier: str, count: int, average_incl_tax: Decimal | None)`
  - `get_supplier_history(repo, supplier: str) -> SupplierStats` (factures **reçues** uniquement ; devis et factures émises exclus)
  - `MIN_HISTORY = 3`, `UNUSUAL_FACTOR = Decimal("3")`
  - `check_unusual_amount(invoice: Invoice, stats: SupplierStats) -> Issue | None` (code `MONTANT_INHABITUEL` ; toujours `None` pour une facture émise)

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_history.py` :

```python
from decimal import Decimal

from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from agent_factures.tools.history import (
    SupplierStats,
    check_unusual_amount,
    find_duplicates,
    get_supplier_history,
)
from tests.factories import make_invoice


def repo_with(*invoices) -> InvoiceRepository:
    repo = InvoiceRepository(connect())
    for i, invoice in enumerate(invoices):
        repo.add(invoice, f"{i}.pdf")
    return repo


def test_find_duplicates_matches_supplier_and_number():
    repo = repo_with(make_invoice(number="F-1"), make_invoice(number="F-2"))
    assert len(find_duplicates(repo, "BUREAU PLUS SARL", "F-1")) == 1
    assert find_duplicates(repo, "Bureau Plus SARL", "F-3") == []


def test_supplier_history_averages_received_invoices_only():
    repo = repo_with(
        make_invoice(number="1", amount_incl_tax=Decimal("100")),
        make_invoice(number="2", amount_incl_tax=Decimal("110")),
        make_invoice(number="3", amount_incl_tax=Decimal("120")),
        make_invoice(number="D1", doc_type="devis", amount_incl_tax=Decimal("9999")),
        make_invoice(number="E1", direction="emise", amount_incl_tax=Decimal("9999")),
    )
    stats = get_supplier_history(repo, "Bureau Plus SARL")
    assert stats.count == 3
    assert stats.average_incl_tax == Decimal("110")


def test_unknown_supplier_has_empty_history():
    stats = get_supplier_history(repo_with(), "Inconnu")
    assert stats == SupplierStats(supplier="Inconnu", count=0, average_incl_tax=None)


def test_unusual_amount_requires_three_invoices_and_strictly_more_than_triple():
    stats = SupplierStats(supplier="X", count=3, average_incl_tax=Decimal("100"))
    issue = check_unusual_amount(make_invoice(amount_incl_tax=Decimal("301")), stats)
    assert issue is not None and issue.code == "MONTANT_INHABITUEL"
    assert check_unusual_amount(make_invoice(amount_incl_tax=Decimal("300")), stats) is None
    short = SupplierStats(supplier="X", count=2, average_incl_tax=Decimal("100"))
    assert check_unusual_amount(make_invoice(amount_incl_tax=Decimal("1000")), short) is None


def test_issued_invoices_are_never_unusual():
    stats = SupplierStats(supplier="X", count=5, average_incl_tax=Decimal("100"))
    assert check_unusual_amount(make_invoice(direction="emise", amount_incl_tax=Decimal("5000")), stats) is None
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_history.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.tools.history'`

- [ ] **Step 3 : implémenter**

`src/agent_factures/tools/history.py` :

```python
"""Vérifications qui s'appuient sur les factures déjà enregistrées (lecture seule)."""

from decimal import Decimal

from pydantic import BaseModel

from agent_factures.extraction.models import Direction, DocumentType, Invoice, Issue
from agent_factures.storage.repository import InvoiceRepository, StoredInvoice

MIN_HISTORY = 3
UNUSUAL_FACTOR = Decimal("3")


class SupplierStats(BaseModel):
    supplier: str
    count: int
    average_incl_tax: Decimal | None


def find_duplicates(repo: InvoiceRepository, supplier: str, number: str) -> list[StoredInvoice]:
    return repo.find_by_supplier_and_number(supplier, number)


def get_supplier_history(repo: InvoiceRepository, supplier: str) -> SupplierStats:
    invoices = [
        s.invoice
        for s in repo.list_by_supplier(supplier)
        if s.invoice.doc_type is DocumentType.INVOICE and s.invoice.direction is Direction.RECEIVED
    ]
    if not invoices:
        return SupplierStats(supplier=supplier, count=0, average_incl_tax=None)
    total = sum((i.amount_incl_tax for i in invoices), Decimal("0"))
    return SupplierStats(supplier=supplier, count=len(invoices), average_incl_tax=total / len(invoices))


def check_unusual_amount(invoice: Invoice, stats: SupplierStats) -> Issue | None:
    if invoice.direction is Direction.ISSUED or stats.count < MIN_HISTORY or stats.average_incl_tax is None:
        return None
    threshold = stats.average_incl_tax * UNUSUAL_FACTOR
    if invoice.amount_incl_tax <= threshold:
        return None
    return Issue(
        code="MONTANT_INHABITUEL",
        message=(
            f"Montant de {invoice.amount_incl_tax} € TTC, plus de 3 fois la moyenne "
            f"({stats.average_incl_tax:.2f} €) des {stats.count} factures précédentes de ce fournisseur."
        ),
    )
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_history.py -v`
Expected : 5 passed

- [ ] **Step 5 : commit**

```bash
git add -A
git commit -m "feat: détection des doublons et des montants inhabituels" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5 : chargement des documents et schémas des outils

**Files :**
- Create : `src/agent_factures/agent/__init__.py`, `src/agent_factures/agent/documents.py`, `src/agent_factures/agent/tool_defs.py`
- Test : `tests/test_documents.py`, `tests/test_tool_defs.py`

**Interfaces :**
- Consumes : `Invoice`, `Status` (Task 1)
- Produces :
  - `DocumentError(ValueError)`
  - `load_document(path: Path) -> dict` : bloc `{"type": "document"|"image", "source": {"type": "base64", "media_type": ..., "data": ...}}`
  - `INVOICE_SCHEMA: dict`, `VERDICT_SCHEMA: dict`, `TOOLS: list[dict]`, `TOOL_NAMES: set[str]` = `{"submit_extraction", "check_amounts", "check_due_date", "find_duplicates", "get_supplier_history", "submit_verdict"}`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_documents.py` :

```python
import base64

import pytest

from agent_factures.agent.documents import DocumentError, load_document


def test_pdf_becomes_document_block(tmp_path):
    path = tmp_path / "f.PDF"
    path.write_bytes(b"%PDF-1.4 fake")
    block = load_document(path)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == b"%PDF-1.4 fake"


@pytest.mark.parametrize(("suffix", "media_type"), [(".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg")])
def test_images_become_image_blocks(tmp_path, suffix, media_type):
    path = tmp_path / f"scan{suffix}"
    path.write_bytes(b"img")
    block = load_document(path)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == media_type


def test_unsupported_format_raises(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    with pytest.raises(DocumentError, match="Format non supporté"):
        load_document(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(DocumentError, match="illisible"):
        load_document(tmp_path / "absent.pdf")
```

`tests/test_tool_defs.py` :

```python
from agent_factures.agent.tool_defs import INVOICE_SCHEMA, TOOL_NAMES, TOOLS, VERDICT_SCHEMA
from agent_factures.extraction.models import Invoice, Status


def test_invoice_schema_covers_every_model_field():
    assert set(INVOICE_SCHEMA["properties"]) == set(Invoice.model_fields)


def test_invoice_schema_requires_the_model_required_fields():
    model_required = {name for name, field in Invoice.model_fields.items() if field.is_required()}
    assert set(INVOICE_SCHEMA["required"]) == model_required


def test_verdict_schema_lists_all_statuses():
    assert VERDICT_SCHEMA["properties"]["status"]["enum"] == [s.value for s in Status]


def test_tools_are_well_formed_and_unique():
    names = [tool["name"] for tool in TOOLS]
    assert len(names) == len(set(names))
    assert set(names) == TOOL_NAMES
    for tool in TOOLS:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_documents.py tests/test_tool_defs.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.agent'`

- [ ] **Step 3 : implémenter**

```bash
mkdir -p src/agent_factures/agent && touch src/agent_factures/agent/__init__.py
```

`src/agent_factures/agent/documents.py` :

```python
"""Transforme un fichier en bloc de contenu pour l'API Messages."""

import base64
from pathlib import Path

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class DocumentError(ValueError):
    pass


def load_document(path: Path) -> dict:
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise DocumentError(f"Format non supporté : {path.suffix or 'sans extension'} (formats acceptés : PDF, PNG, JPG).")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DocumentError(f"Fichier illisible : {path.name} ({exc.strerror}).") from exc
    block_type = "document" if media_type == "application/pdf" else "image"
    return {
        "type": block_type,
        "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(raw).decode("ascii")},
    }
```

`src/agent_factures/agent/tool_defs.py` :

```python
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
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_documents.py tests/test_tool_defs.py -v`
Expected : 10 passed

- [ ] **Step 5 : commit**

```bash
git add -A
git commit -m "feat: chargement des documents et schémas des outils de l'agent" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6 : exécuteur d'outils

**Files :**
- Create : `src/agent_factures/agent/executor.py`
- Test : `tests/test_executor.py`

**Interfaces :**
- Consumes : `Invoice`, `Issue`, `Status`, `Verdict` (Task 1) ; `InvoiceRepository`, `connect` (Task 2) ; `check_amounts`, `check_due_date` (Task 3) ; `find_duplicates`, `get_supplier_history`, `check_unusual_amount` (Task 4)
- Produces :
  - `ToolCall(name: str, input: dict, output: str, is_error: bool)` (dataclass)
  - `ToolExecutor(repo, today)` avec :
    - `execute(name: str, tool_input: dict) -> tuple[str, bool]` (sortie texte, is_error)
    - attributs `invoice: Invoice | None`, `partial_extraction: dict | None`, `verdict: Verdict | None`, `issues: list[Issue]` (dédoublonnés par code), `trace: list[ToolCall]`
    - `MAX_EXTRACTION_ATTEMPTS = 2`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_executor.py` :

```python
import json
from datetime import date
from decimal import Decimal

from agent_factures.agent.executor import ToolExecutor
from agent_factures.extraction.models import Status
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice

TODAY = date(2026, 9, 24)
VALID = json.loads(make_invoice().model_dump_json())


def make_executor(*stored) -> ToolExecutor:
    repo = InvoiceRepository(connect())
    for i, invoice in enumerate(stored):
        repo.add(invoice, f"{i}.pdf")
    return ToolExecutor(repo, TODAY)


def test_unknown_tool_is_an_error():
    executor = make_executor()
    output, is_error = executor.execute("delete_everything", {})
    assert is_error and "inconnu" in output


def test_checks_before_extraction_are_refused():
    executor = make_executor()
    output, is_error = executor.execute("check_amounts", {})
    assert is_error and "submit_extraction" in output


def test_valid_extraction_then_clean_checks():
    executor = make_executor()
    assert executor.execute("submit_extraction", VALID) == ("Extraction enregistrée.", False)
    assert executor.invoice is not None
    output, is_error = executor.execute("check_amounts", {})
    assert not is_error and json.loads(output) == []
    assert executor.issues == []


def test_invalid_extraction_gets_one_retry_then_needs_review():
    executor = make_executor()
    bad = {**VALID, "supplier": ""}
    output, is_error = executor.execute("submit_extraction", bad)
    assert is_error and "corrige" in output
    assert executor.verdict is None
    output, is_error = executor.execute("submit_extraction", bad)
    assert is_error
    assert executor.verdict is not None and executor.verdict.status is Status.NEEDS_REVIEW
    assert executor.partial_extraction == bad
    assert executor.invoice is None


def test_amount_issue_is_collected():
    executor = make_executor()
    executor.execute("submit_extraction", {**VALID, "vat_amount": 25})
    output, _ = executor.execute("check_amounts", {})
    assert json.loads(output)[0]["code"] == "TOTAL_INCOHERENT"
    assert [i.code for i in executor.issues] == ["TOTAL_INCOHERENT"]


def test_duplicate_is_detected():
    executor = make_executor(make_invoice())
    executor.execute("submit_extraction", VALID)
    output, is_error = executor.execute("find_duplicates", {})
    assert not is_error
    assert json.loads(output)["doublons"][0]["fichier"] == "0.pdf"
    assert [i.code for i in executor.issues] == ["DOUBLON"]


def test_supplier_history_flags_unusual_amount():
    history = [make_invoice(number=str(n), amount_incl_tax=Decimal("100")) for n in range(3)]
    executor = make_executor(*history)
    executor.execute("submit_extraction", {**VALID, "amount_excl_tax": 1000, "vat_amount": 200, "amount_incl_tax": 1200, "lines": []})
    output, _ = executor.execute("get_supplier_history", {})
    payload = json.loads(output)
    assert payload["nombre_factures"] == 3
    assert payload["alerte"]["code"] == "MONTANT_INHABITUEL"
    assert [i.code for i in executor.issues] == ["MONTANT_INHABITUEL"]


def test_overdue_is_detected():
    executor = make_executor()
    executor.execute("submit_extraction", {**VALID, "due_date": "2026-09-01"})
    output, _ = executor.execute("check_due_date", {})
    assert json.loads(output)["code"] == "ECHEANCE_DEPASSEE"


def test_same_issue_is_not_collected_twice():
    executor = make_executor()
    executor.execute("submit_extraction", {**VALID, "vat_amount": 25})
    executor.execute("check_amounts", {})
    executor.execute("check_amounts", {})
    assert len(executor.issues) == 1


def test_verdict_validation():
    executor = make_executor()
    output, is_error = executor.execute("submit_verdict", {"status": "parfait", "explanation": "?"})
    assert is_error and executor.verdict is None
    output, is_error = executor.execute("submit_verdict", {"status": "ok", "explanation": "Tout est correct."})
    assert not is_error and executor.verdict.status is Status.OK


def test_every_call_is_traced():
    executor = make_executor()
    executor.execute("check_amounts", {})
    executor.execute("submit_extraction", VALID)
    assert [(c.name, c.is_error) for c in executor.trace] == [("check_amounts", True), ("submit_extraction", False)]
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_executor.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.agent.executor'`

- [ ] **Step 3 : implémenter**

`src/agent_factures/agent/executor.py` :

```python
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
        output, is_error = handler(tool_input) if handler else (f"Outil inconnu : {name}.", True)
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
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_executor.py -v`
Expected : 11 passed

- [ ] **Step 5 : commit**

```bash
git add -A
git commit -m "feat: exécuteur des outils de l'agent" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7 : boucle agentique

**Files :**
- Create : `src/agent_factures/agent/loop.py`
- Test : `tests/fakes.py`, `tests/test_loop.py`

**Interfaces :**
- Consumes : `load_document`, `DocumentError` (Task 5) ; `TOOLS` (Task 5) ; `ToolExecutor`, `ToolCall` (Task 6) ; `Invoice`, `Issue`, `Status`, `Verdict` (Task 1) ; `InvoiceRepository` (Task 2)
- Produces :
  - `MODELS = ["claude-sonnet-5", "claude-haiku-4-5"]`, `DEFAULT_MODEL = "claude-sonnet-5"`, `PRICES_PER_MTOK: dict[str, tuple[float, float]]`
  - `DEFAULT_COMPANY = "Atelier Lumière SAS"`, `SYSTEM_PROMPT_TEMPLATE: str` (contient `{company}`), `USER_INSTRUCTION: str`
  - `AgentResult` (dataclass) : `invoice: Invoice | None`, `partial_extraction: dict | None`, `verdict: Verdict`, `issues: list[Issue]`, `trace: list[ToolCall]`, `input_tokens: int`, `output_tokens: int`, `cost_usd: float | None`
  - `InvoiceAgent(client, repo, model=DEFAULT_MODEL, today: date | None = None, max_iterations: int = 10, company: str = DEFAULT_COMPANY)` avec `process(path: Path) -> AgentResult`
  - `tests.fakes` : `tool_use(name, tool_input, id=None)`, `reply(*blocks, stop_reason="tool_use", input_tokens=100, output_tokens=50)`, `FakeClient(responses)` avec `.calls`

- [ ] **Step 1 : écrire le client factice et les tests qui échouent**

`tests/fakes.py` :

```python
"""Client Anthropic factice : renvoie des réponses scriptées, n'appelle jamais le réseau."""

from itertools import count
from types import SimpleNamespace

_ids = count(1)


def tool_use(name: str, tool_input: dict, id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id or f"toolu_{next(_ids)}", name=name, input=tool_input)


def reply(*blocks, stop_reason: str = "tool_use", input_tokens: int = 100, output_tokens: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
```

`tests/test_loop.py` :

```python
import json
from datetime import date
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from agent_factures.agent.loop import InvoiceAgent
from agent_factures.extraction.models import Status
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice
from tests.fakes import FakeClient, reply, tool_use

TODAY = date(2026, 9, 24)
VALID = json.loads(make_invoice().model_dump_json())


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "facture.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def run(responses, path, **kwargs):
    repo = InvoiceRepository(connect())
    client = FakeClient(responses)
    agent = InvoiceAgent(client=client, repo=repo, today=TODAY, **kwargs)
    return agent.process(path), client, repo


def test_happy_path(pdf):
    result, client, repo = run(
        [
            reply(tool_use("submit_extraction", VALID)),
            reply(tool_use("check_amounts", {}, id="a"), tool_use("check_due_date", {}, id="b")),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Facture conforme."})),
        ],
        pdf,
    )
    assert result.verdict.status is Status.OK
    assert result.invoice == make_invoice()
    assert [c.name for c in result.trace] == ["submit_extraction", "check_amounts", "check_due_date", "submit_verdict"]
    assert (result.input_tokens, result.output_tokens) == (300, 150)
    assert result.cost_usd == pytest.approx((300 * 2.0 + 150 * 10.0) / 1_000_000)
    assert len(client.calls) == 3
    first = client.calls[0]
    assert first["model"] == "claude-sonnet-5"
    assert "Atelier Lumière SAS" in first["system"]
    assert first["messages"][0]["content"][0]["type"] == "document"
    results_message = client.calls[2]["messages"][-1]
    assert results_message["role"] == "user"
    assert [r["tool_use_id"] for r in results_message["content"]] == ["a", "b"]
    assert repo.list_all() == []


def test_invalid_extraction_is_retried(pdf):
    result, _, _ = run(
        [
            reply(tool_use("submit_extraction", {**VALID, "supplier": ""})),
            reply(tool_use("submit_extraction", VALID)),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Conforme."})),
        ],
        pdf,
    )
    assert result.invoice is not None
    assert result.verdict.status is Status.OK
    assert result.trace[0].is_error


def test_two_invalid_extractions_stop_the_loop(pdf):
    bad = {**VALID, "supplier": ""}
    result, client, _ = run([reply(tool_use("submit_extraction", bad)), reply(tool_use("submit_extraction", bad))], pdf)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert result.partial_extraction == bad
    assert len(client.calls) == 2


def test_iteration_limit(pdf):
    result, client, _ = run([reply(tool_use("check_amounts", {})) for _ in range(3)], pdf, max_iterations=3)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "Limite de 3 itérations" in result.verdict.explanation
    assert len(client.calls) == 3


def test_stopping_without_verdict_needs_review(pdf):
    text = SimpleNamespace(type="text", text="J'ai fini.")
    result, _, _ = run([reply(text, stop_reason="end_turn")], pdf)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "sans rendre de verdict" in result.verdict.explanation


def test_api_error_needs_review(pdf):
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    result, _, _ = run([error], pdf)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "Erreur d'API" in result.verdict.explanation


def test_unsupported_file_never_calls_claude(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    result, client, _ = run([], path)
    assert result.verdict.status is Status.NEEDS_REVIEW
    assert "Format non supporté" in result.verdict.explanation
    assert client.calls == []


def test_ok_verdict_is_downgraded_when_issues_exist(pdf):
    result, _, _ = run(
        [
            reply(tool_use("submit_extraction", {**VALID, "vat_amount": 25})),
            reply(tool_use("check_amounts", {})),
            reply(tool_use("submit_verdict", {"status": "ok", "explanation": "Conforme."})),
        ],
        pdf,
    )
    assert result.verdict.status is Status.ANOMALY
    assert "TOTAL_INCOHERENT" in result.verdict.explanation


def test_company_name_is_configurable(pdf):
    _, client, _ = run(
        [reply(tool_use("submit_verdict", {"status": "a_revoir", "explanation": "Illisible."}))],
        pdf,
        company="Boulangerie Durand",
    )
    assert "Boulangerie Durand" in client.calls[0]["system"]


def test_unknown_model_has_no_cost(pdf):
    result, _, _ = run(
        [reply(tool_use("submit_verdict", {"status": "a_revoir", "explanation": "Ce n'est pas une facture."}))],
        pdf,
        model="claude-inconnu",
    )
    assert result.cost_usd is None
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_loop.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.agent.loop'`

- [ ] **Step 3 : implémenter**

`src/agent_factures/agent/loop.py` :

```python
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
                return self._result(executor, tokens, fallback="L'agent s'est arrêté sans rendre de verdict.")

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

    def _result(self, executor: ToolExecutor, tokens: list[int], fallback: str | None = None) -> AgentResult:
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
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_loop.py -v`
Expected : 10 passed

- [ ] **Step 5 : lancer toute la suite**

Run : `uv run pytest -v`
Expected : tous les tests passent (60 à ce stade)

- [ ] **Step 6 : commit**

```bash
git add -A
git commit -m "feat: boucle agentique avec garde-fous et suivi du coût" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8 : exports CSV et Excel

**Files :**
- Create : `src/agent_factures/storage/export.py`
- Test : `tests/test_export.py`

**Interfaces :**
- Consumes : `StoredInvoice` (Task 2)
- Produces : `COLUMNS: list[str]`, `to_rows(stored: list[StoredInvoice]) -> list[dict]`, `to_csv_bytes(stored) -> bytes` (séparateur `;`, UTF-8 avec BOM pour Excel FR), `to_excel_bytes(stored) -> bytes`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_export.py` :

```python
from io import BytesIO

import pandas as pd

from agent_factures.storage.export import COLUMNS, to_csv_bytes, to_excel_bytes, to_rows
from agent_factures.storage.repository import StoredInvoice
from tests.factories import make_invoice

STORED = [
    StoredInvoice(id=1, invoice=make_invoice(number="F-1"), source_file="a.pdf"),
    StoredInvoice(id=2, invoice=make_invoice(number="F-2", due_date=None), source_file="b.pdf"),
]


def test_rows_are_flat_and_ordered():
    rows = to_rows(STORED)
    assert list(rows[0]) == COLUMNS
    assert rows[0]["numero"] == "F-1"
    assert rows[0]["sens"] == "recue"
    assert rows[0]["destinataire"] == "Atelier Lumière SAS"
    assert rows[0]["montant_ttc"] == 120.0
    assert rows[1]["echeance"] is None


def test_csv_uses_semicolons_and_bom():
    content = to_csv_bytes(STORED)
    assert content.startswith("﻿".encode("utf-8"))
    header = content.decode("utf-8-sig").splitlines()[0]
    assert header == ";".join(COLUMNS)


def test_excel_roundtrip():
    frame = pd.read_excel(BytesIO(to_excel_bytes(STORED)))
    assert list(frame.columns) == COLUMNS
    assert frame["numero"].tolist() == ["F-1", "F-2"]
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_export.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'agent_factures.storage.export'`

- [ ] **Step 3 : implémenter**

`src/agent_factures/storage/export.py` :

```python
"""Exports tabulaires des pièces enregistrées."""

from io import BytesIO

import pandas as pd

from agent_factures.storage.repository import StoredInvoice

COLUMNS = [
    "id", "type", "sens", "emetteur", "destinataire", "numero", "date_emission", "echeance",
    "montant_ht", "tva", "montant_ttc", "devise", "fichier",
]


def to_rows(stored: list[StoredInvoice]) -> list[dict]:
    return [
        {
            "id": s.id,
            "type": s.invoice.doc_type.value,
            "sens": s.invoice.direction.value,
            "emetteur": s.invoice.supplier,
            "destinataire": s.invoice.customer,
            "numero": s.invoice.number,
            "date_emission": s.invoice.issue_date.isoformat(),
            "echeance": s.invoice.due_date.isoformat() if s.invoice.due_date else None,
            "montant_ht": float(s.invoice.amount_excl_tax),
            "tva": float(s.invoice.vat_amount),
            "montant_ttc": float(s.invoice.amount_incl_tax),
            "devise": s.invoice.currency,
            "fichier": s.source_file,
        }
        for s in stored
    ]


def _frame(stored: list[StoredInvoice]) -> pd.DataFrame:
    return pd.DataFrame(to_rows(stored), columns=COLUMNS)


def to_csv_bytes(stored: list[StoredInvoice]) -> bytes:
    return _frame(stored).to_csv(index=False, sep=";").encode("utf-8-sig")


def to_excel_bytes(stored: list[StoredInvoice]) -> bytes:
    buffer = BytesIO()
    _frame(stored).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_export.py -v`
Expected : 3 passed

- [ ] **Step 5 : commit**

```bash
git add -A
git commit -m "feat: exports CSV et Excel" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9 : interface Streamlit

**Files :**
- Create : `app/main.py`
- Test : `tests/test_app.py`

**Interfaces :**
- Consumes : `InvoiceAgent`, `AgentResult`, `MODELS`, `DEFAULT_MODEL` (Task 7) ; `Invoice`, `DocumentType`, `Status` (Task 1) ; `connect`, `InvoiceRepository`, `ActionLog` (Task 2) ; `to_rows`, `to_csv_bytes`, `to_excel_bytes` (Task 8) ; `draft_reminder` (Task 3)
- Produces : application lancée par `uv run streamlit run app/main.py`. Variables d'environnement `AGENT_FACTURES_DB` (défaut `data/factures.db`) et `COMPANY_NAME` (défaut `DEFAULT_COMPANY`).

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_app.py` :

```python
from streamlit.testing.v1 import AppTest

from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice


def test_app_starts_on_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_FACTURES_DB", str(tmp_path / "empty.db"))
    at = AppTest.from_file("app/main.py", default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Agent factures"


def test_dashboard_shows_stored_invoices(tmp_path, monkeypatch):
    db_path = tmp_path / "seeded.db"
    InvoiceRepository(connect(str(db_path))).add(make_invoice(), "a.pdf")
    monkeypatch.setenv("AGENT_FACTURES_DB", str(db_path))
    at = AppTest.from_file("app/main.py", default_timeout=30).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["À payer (fournisseurs, TTC)"] == "120,00 €"
    assert metrics["À encaisser (clients, TTC)"] == "0,00 €"
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_app.py -v`
Expected : FAIL (fichier `app/main.py` introuvable)

- [ ] **Step 3 : implémenter**

```bash
mkdir -p app
```

`app/main.py` :

```python
"""Interface Streamlit : dépôt, validation humaine, tableau de bord et journal."""

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import anthropic
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from agent_factures.agent.loop import DEFAULT_COMPANY, DEFAULT_MODEL, MODELS, AgentResult, InvoiceAgent
from agent_factures.extraction.models import Direction, DocumentType, Invoice, Status
from agent_factures.storage.action_log import ActionLog
from agent_factures.storage.db import connect
from agent_factures.storage.export import to_csv_bytes, to_excel_bytes, to_rows
from agent_factures.storage.repository import InvoiceRepository
from agent_factures.tools.reminder import draft_reminder

load_dotenv()

COMPANY = os.environ.get("COMPANY_NAME", DEFAULT_COMPANY)
UPLOAD_DIR = Path("data/uploads")
INBOX_DIR = Path("inbox")
ACCEPTED_TYPES = ["pdf", "png", "jpg", "jpeg"]
STATUS_LABELS = {Status.OK: "✅ OK", Status.ANOMALY: "⚠️ Anomalie", Status.NEEDS_REVIEW: "❓ À revoir"}


def euros(amount: Decimal) -> str:
    return f"{amount:,.2f} €".replace(",", " ").replace(".", ",")


@st.cache_resource
def get_connection(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return connect(path)


def process_files(paths: list[Path], repo: InvoiceRepository, log: ActionLog, model: str) -> None:
    try:
        agent = InvoiceAgent(client=anthropic.Anthropic(), repo=repo, model=model, company=COMPANY)
    except anthropic.AnthropicError as exc:
        st.error(f"Client Claude indisponible : {exc}. Vérifie ANTHROPIC_API_KEY dans le fichier .env.")
        return
    pending = st.session_state.setdefault("pending", {})
    for path in paths:
        with st.status(f"Analyse de {path.name}…", expanded=True) as box:
            result = agent.process(path)
            for call in result.trace:
                box.write(f"🔧 `{call.name}` → {call.output[:200]}")
            box.update(label=f"{path.name} : {STATUS_LABELS[result.verdict.status]}", state="complete", expanded=False)
        log.record(
            path.name,
            "analyse",
            {
                "statut": result.verdict.status.value,
                "outils": [c.name for c in result.trace],
                "tokens": result.input_tokens + result.output_tokens,
                "cout_usd": result.cost_usd,
            },
        )
        pending[path.name] = (path, result)


def _default(result: AgentResult, field: str):
    if result.invoice is not None:
        return getattr(result.invoice, field)
    return (result.partial_extraction or {}).get(field)


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def render_review(name: str, path: Path, result: AgentResult, repo: InvoiceRepository, log: ActionLog) -> None:
    with st.container(border=True):
        st.subheader(f"{name} — {STATUS_LABELS[result.verdict.status]}")
        st.write(result.verdict.explanation)
        for issue in result.issues:
            st.warning(f"**{issue.code}** : {issue.message}")
        cost = f"{result.cost_usd:.4f} $" if result.cost_usd is not None else "inconnu"
        st.caption(f"{result.input_tokens} tokens en entrée · {result.output_tokens} en sortie · coût ≈ {cost}")
        if result.invoice is None:
            st.info("Pas d'extraction valide : complète les champs à la main ou rejette le document.")

        doc_types = [t.value for t in DocumentType]
        current_type = str(_default(result, "doc_type") or DocumentType.INVOICE.value)
        directions = [d.value for d in Direction]
        current_direction = str(_default(result, "direction") or Direction.RECEIVED.value)
        with st.form(f"form-{name}"):
            col_type, col_direction = st.columns(2)
            doc_type = col_type.selectbox(
                "Type", doc_types, index=doc_types.index(current_type) if current_type in doc_types else 0
            )
            direction = col_direction.selectbox(
                "Sens",
                directions,
                index=directions.index(current_direction) if current_direction in directions else 0,
                format_func=lambda d: "Reçue (fournisseur)" if d == Direction.RECEIVED.value else "Émise (client)",
            )
            col_from, col_to = st.columns(2)
            supplier = col_from.text_input("Émetteur", value=str(_default(result, "supplier") or ""))
            customer = col_to.text_input("Destinataire", value=str(_default(result, "customer") or ""))
            number = st.text_input("Numéro", value=str(_default(result, "number") or ""))
            col1, col2 = st.columns(2)
            issue_date = col1.date_input("Date d'émission", value=_as_date(_default(result, "issue_date")), format="DD/MM/YYYY")
            due_date = col2.date_input("Échéance", value=_as_date(_default(result, "due_date")), format="DD/MM/YYYY")
            col3, col4, col5 = st.columns(3)
            ht = col3.number_input("HT", value=_as_float(_default(result, "amount_excl_tax")), step=0.01, format="%.2f")
            tva = col4.number_input("TVA", value=_as_float(_default(result, "vat_amount")), step=0.01, format="%.2f")
            ttc = col5.number_input("TTC", value=_as_float(_default(result, "amount_incl_tax")), step=0.01, format="%.2f")
            accept = st.form_submit_button("Accepter", type="primary")
            reject = st.form_submit_button("Rejeter")

        if accept:
            try:
                invoice = Invoice(
                    doc_type=doc_type,
                    direction=direction,
                    supplier=supplier,
                    customer=customer or None,
                    number=number,
                    issue_date=issue_date,
                    due_date=due_date,
                    amount_excl_tax=Decimal(f"{ht:.2f}"),
                    vat_amount=Decimal(f"{tva:.2f}"),
                    amount_incl_tax=Decimal(f"{ttc:.2f}"),
                    lines=result.invoice.lines if result.invoice else [],
                )
            except ValidationError as exc:
                st.error(f"Champs invalides : {exc}")
                return
            invoice_id = repo.add(invoice, source_file=str(path))
            log.record(name, "accepte", {"id": invoice_id, "corrige": invoice != result.invoice})
            del st.session_state["pending"][name]
            st.rerun()
        if reject:
            log.record(name, "rejete")
            del st.session_state["pending"][name]
            st.rerun()


def render_process_tab(repo: InvoiceRepository, log: ActionLog, model: str) -> None:
    uploads = st.file_uploader("Dépose des factures ou devis", type=ACCEPTED_TYPES, accept_multiple_files=True)
    col1, col2 = st.columns(2)
    if col1.button("Analyser les fichiers déposés", disabled=not uploads):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        paths = []
        for upload in uploads:
            path = UPLOAD_DIR / upload.name
            path.write_bytes(upload.getvalue())
            paths.append(path)
        process_files(paths, repo, log, model)
    if col2.button("Traiter le dossier inbox/"):
        paths = sorted(p for p in INBOX_DIR.glob("*") if p.is_file() and not p.name.startswith("."))
        if paths:
            process_files(paths, repo, log, model)
        else:
            st.info("Le dossier inbox/ est vide.")

    for name, (path, result) in list(st.session_state.get("pending", {}).items()):
        render_review(name, path, result, repo, log)


def render_dashboard(repo: InvoiceRepository, today: date) -> None:
    stored = repo.list_all()
    invoices = [s for s in stored if s.invoice.doc_type is DocumentType.INVOICE]
    to_pay = sum((s.invoice.amount_incl_tax for s in invoices if s.invoice.direction is Direction.RECEIVED), Decimal("0"))
    to_collect = sum((s.invoice.amount_incl_tax for s in invoices if s.invoice.direction is Direction.ISSUED), Decimal("0"))
    upcoming = [s for s in invoices if s.invoice.due_date and today <= s.invoice.due_date <= today + timedelta(days=30)]
    late_suppliers = repo.list_overdue(today, direction=Direction.RECEIVED)
    late_customers = repo.list_overdue(today, direction=Direction.ISSUED)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("À payer (fournisseurs, TTC)", euros(to_pay))
    col2.metric("À encaisser (clients, TTC)", euros(to_collect))
    col3.metric("Échéances sous 30 jours", len(upcoming))
    col4.metric("Factures en retard", len(late_suppliers) + len(late_customers))

    if late_customers:
        st.subheader("Clients en retard de paiement")
        for s in late_customers:
            with st.expander(f"{s.invoice.customer or 'Client'} — n° {s.invoice.number} — {euros(s.invoice.amount_incl_tax)}"):
                st.caption("Brouillon de relance (rien n'est envoyé automatiquement) :")
                st.code(draft_reminder(s.invoice, today), language=None)

    if late_suppliers:
        st.subheader("Factures fournisseurs à payer en retard")
        for s in late_suppliers:
            st.warning(
                f"{s.invoice.supplier} — n° {s.invoice.number} — {euros(s.invoice.amount_incl_tax)}, "
                f"échue le {s.invoice.due_date:%d/%m/%Y}"
            )

    st.subheader("Pièces enregistrées")
    if not stored:
        st.info("Aucune pièce enregistrée pour l'instant.")
        return
    st.dataframe(pd.DataFrame(to_rows(stored)), hide_index=True)
    col_csv, col_xlsx = st.columns(2)
    col_csv.download_button("Exporter en CSV", to_csv_bytes(stored), "factures.csv", "text/csv")
    col_xlsx.download_button(
        "Exporter en Excel",
        to_excel_bytes(stored),
        "factures.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def render_log_tab(log: ActionLog) -> None:
    entries = log.list_recent(limit=200)
    if not entries:
        st.info("Le journal est vide.")
        return
    st.dataframe(pd.DataFrame([e.model_dump() for e in entries]), hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Agent factures", page_icon="🧾", layout="wide")
    st.title("Agent factures")
    st.caption("Extraction, contrôle et suivi de vos factures fournisseurs. Rien n'est enregistré sans votre validation.")

    conn = get_connection(os.environ.get("AGENT_FACTURES_DB", "data/factures.db"))
    repo, log = InvoiceRepository(conn), ActionLog(conn)
    model = st.sidebar.selectbox("Modèle Claude", MODELS, index=MODELS.index(DEFAULT_MODEL))

    tab_process, tab_dashboard, tab_log = st.tabs(["Traiter", "Tableau de bord", "Journal"])
    with tab_process:
        render_process_tab(repo, log, model)
    with tab_dashboard:
        render_dashboard(repo, date.today())
    with tab_log:
        render_log_tab(log)


main()
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_app.py -v`
Expected : 2 passed

- [ ] **Step 5 : vérification manuelle**

Run : `uv run streamlit run app/main.py` puis ouvrir http://localhost:8501.
Expected : les trois onglets s'affichent sans erreur. Le traitement réel d'un document nécessite `ANTHROPIC_API_KEY` dans `.env` (à faire par l'utilisateur).

- [ ] **Step 6 : commit**

```bash
git add -A
git commit -m "feat: interface Streamlit (dépôt, validation, tableau de bord, journal)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10 : génération du jeu d'évaluation

**Files :**
- Create : `evals/__init__.py`, `evals/generate.py`, `evals/dataset/` (généré et commité)
- Test : `tests/test_generate.py`

**Interfaces :**
- Consumes : rien du package (volontairement indépendant, pour ne pas biaiser les evals)
- Produces :
  - `evals.generate.TODAY = date(2026, 9, 24)`
  - `evals.generate.build_specs() -> list[dict]` : 20 entrées dans l'ordre de traitement
  - `evals.generate.generate(out_dir: Path) -> list[dict]` : écrit les fichiers et `expected.json`
  - Format de `expected.json` : `{"today": "2026-09-24", "documents": [{"file": str, "expected_status": "ok"|"anomalie"|"a_revoir", "expected_issues": [str], "accept": bool, "invoice": {doc_type, direction, supplier, customer, number, issue_date, due_date, amount_excl_tax, vat_amount, amount_incl_tax} | null}]}`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_generate.py` :

```python
import json
from collections import Counter
from decimal import Decimal

from evals.generate import build_specs, generate


def test_dataset_composition_matches_spec():
    specs = build_specs()
    assert len(specs) == 20
    issues = Counter(code for s in specs for code in s["expected_issues"])
    assert issues["DOUBLON"] == 2
    assert issues["TOTAL_INCOHERENT"] == 2
    assert issues["MONTANT_INHABITUEL"] == 1
    assert sum(1 for s in specs if s["invoice"] and s["invoice"]["doc_type"] == "devis") == 2
    assert sum(1 for s in specs if s["invoice"] is None) == 1
    assert sum(1 for s in specs if s["file"].endswith(".png")) == 1
    issued = [s for s in specs if s["invoice"] and s["invoice"]["direction"] == "emise"]
    assert len(issued) == 2
    assert sum(1 for s in issued if "ECHEANCE_DEPASSEE" in s["expected_issues"]) == 1


def test_statuses_follow_issues():
    for s in build_specs():
        if s["invoice"] is None:
            assert s["expected_status"] == "a_revoir"
        elif s["expected_issues"]:
            assert s["expected_status"] == "anomalie"
        else:
            assert s["expected_status"] == "ok"


def test_consistent_documents_add_up():
    for s in build_specs():
        inv = s["invoice"]
        if inv and "TOTAL_INCOHERENT" not in s["expected_issues"]:
            total = Decimal(inv["amount_excl_tax"]) + Decimal(inv["vat_amount"])
            assert total == Decimal(inv["amount_incl_tax"]), s["file"]


def test_generate_writes_files_and_expected_json(tmp_path):
    generate(tmp_path)
    expected = json.loads((tmp_path / "expected.json").read_text())
    assert expected["today"] == "2026-09-24"
    for doc in expected["documents"]:
        path = tmp_path / doc["file"]
        assert path.exists() and path.stat().st_size > 500, doc["file"]
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_generate.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'evals.generate'`

- [ ] **Step 3 : implémenter**

```bash
mkdir -p evals && touch evals/__init__.py
```

`evals/generate.py` :

```python
"""Génère un jeu de factures fictives avec leurs valeurs attendues.

Usage : uv run python -m evals.generate
"""

import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

TODAY = date(2026, 9, 24)
COMPANY = "Atelier Lumière SAS"
DATASET_DIR = Path(__file__).parent / "dataset"
CENT = Decimal("0.01")
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]

ADDRESSES = {
    COMPANY: "12 rue des Arts, 69002 Lyon",
    "Bureau Plus SARL": "8 avenue Jean Jaurès, 69007 Lyon",
    "Imprimerie Dupont": "45 rue Garibaldi, 69003 Lyon",
    "TechNet Services": "3 place Bellecour, 69002 Lyon",
    "Transports Martin": "Zone Industrielle Nord, 69120 Vaulx-en-Velin",
    "Hôtel Bellevue": "2 quai Saint-Antoine, 69002 Lyon",
    "Café des Arts": "7 rue Mercière, 69002 Lyon",
}


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def doc(file, supplier, number, issue, lines, *, doc_type="facture", due_days=30,
        vat_error=None, issues=(), accept=True, direction="recue", customer=COMPANY):
    ht = sum((money(q * money(p)) for _, q, p in lines), Decimal("0"))
    vat = money(ht * Decimal("0.20"))
    ttc = ht + vat
    printed_vat = vat + vat_error if vat_error is not None else vat
    due = issue + timedelta(days=due_days) if doc_type == "facture" else None
    codes = list(issues)
    if due is not None and due < TODAY and "ECHEANCE_DEPASSEE" not in codes:
        codes.append("ECHEANCE_DEPASSEE")
    return {
        "file": file,
        "expected_status": "anomalie" if codes else "ok",
        "expected_issues": codes,
        "accept": accept,
        "invoice": {
            "doc_type": doc_type,
            "direction": direction,
            "supplier": supplier,
            "customer": customer,
            "number": number,
            "issue_date": issue.isoformat(),
            "due_date": due.isoformat() if due else None,
            "amount_excl_tax": str(ht),
            "vat_amount": str(printed_vat),
            "amount_incl_tax": str(ttc),
        },
        "lines": [[label, qty, str(money(price))] for label, qty, price in lines],
    }


def build_specs() -> list[dict]:
    d = date
    return [
        doc("01_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-101", d(2026, 9, 2),
            [("Ramettes papier A4", 20, 4.5), ("Stylos bille (boîte)", 5, 12.9), ("Classeurs", 10, 3.2)]),
        doc("02_dupont.pdf", "Imprimerie Dupont", "4512", d(2026, 9, 3),
            [("Flyers A5 x1000", 2, 89.0), ("Cartes de visite x500", 1, 45.0)]),
        doc("03_technet.pdf", "TechNet Services", "TN-889", d(2026, 9, 4),
            [("Maintenance informatique septembre", 1, 350.0)]),
        doc("04_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-118", d(2026, 9, 8),
            [("Cartouches d'encre", 4, 38.0), ("Post-it (lot)", 6, 5.5)]),
        doc("05_martin.pdf", "Transports Martin", "TM/26/033", d(2026, 8, 11),
            [("Livraison Lyon - Grenoble", 1, 280.0), ("Manutention", 2, 35.0)]),
        doc("06_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-131", d(2026, 9, 12),
            [("Chaises de bureau", 1, 189.0), ("Lampe LED", 2, 29.9)]),
        doc("07_dupont_scan.png", "Imprimerie Dupont", "4580", d(2026, 9, 14),
            [("Affiches A2 x50", 1, 160.0)]),
        doc("08_technet_tva.pdf", "TechNet Services", "TN-902", d(2026, 9, 15),
            [("Licence antivirus (12 mois)", 10, 24.0)], vat_error=Decimal("12.00"),
            issues=["TOTAL_INCOHERENT"], accept=False),
        doc("09_bureau_plus_doublon.pdf", "Bureau Plus SARL", "F-2026-101", d(2026, 9, 2),
            [("Ramettes papier A4", 20, 4.5), ("Stylos bille (boîte)", 5, 12.9), ("Classeurs", 10, 3.2)],
            issues=["DOUBLON"], accept=False),
        doc("10_dupont_devis.pdf", "Imprimerie Dupont", "D-2026-044", d(2026, 9, 16),
            [("Brochures 16 pages x500", 1, 740.0)], doc_type="devis"),
        doc("11_martin.pdf", "Transports Martin", "TM/26/041", d(2026, 9, 1),
            [("Livraison Lyon - Annecy", 1, 240.0)]),
        doc("12_bureau_plus_inhabituel.pdf", "Bureau Plus SARL", "F-2026-150", d(2026, 9, 18),
            [("Bureaux assis-debout", 8, 495.0)], issues=["MONTANT_INHABITUEL"]),
        doc("13_emise_bellevue.pdf", COMPANY, "AL-2026-057", d(2026, 8, 5),
            [("Luminaires sur mesure", 3, 420.0), ("Pose", 1, 180.0)],
            direction="emise", customer="Hôtel Bellevue"),
        {
            "file": "14_courrier.pdf",
            "expected_status": "a_revoir",
            "expected_issues": [],
            "accept": False,
            "invoice": None,
            "letter": True,
        },
        doc("15_dupont_tva.pdf", "Imprimerie Dupont", "4633", d(2026, 9, 20),
            [("Kakémono 80x200", 2, 115.0)], vat_error=Decimal("-18.40"),
            issues=["TOTAL_INCOHERENT"], accept=False),
        doc("16_martin_doublon.pdf", "Transports Martin", "TM/26/033", d(2026, 8, 11),
            [("Livraison Lyon - Grenoble", 1, 280.0), ("Manutention", 2, 35.0)],
            issues=["DOUBLON"], accept=False),
        doc("17_technet_devis.pdf", "TechNet Services", "DV-310", d(2026, 9, 21),
            [("Remplacement serveur", 1, 2400.0), ("Installation", 1, 450.0)], doc_type="devis"),
        doc("18_bureau_plus.pdf", "Bureau Plus SARL", "F-2026-162", d(2026, 9, 22),
            [("Enveloppes (x500)", 2, 19.0)]),
        doc("19_emise_cafe.pdf", COMPANY, "AL-2026-071", d(2026, 9, 22),
            [("Suspensions design", 4, 145.0)], direction="emise", customer="Café des Arts"),
        doc("20_dupont.pdf", "Imprimerie Dupont", "4701", d(2026, 9, 23),
            [("Étiquettes adhésives x2000", 1, 132.0)]),
    ]


def _fmt_date(value: date, layout: int) -> str:
    return value.strftime("%d/%m/%Y") if layout == 0 else f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def _fmt_money(value: Decimal) -> str:
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",")


def _text_lines(spec: dict, layout: int) -> list[str]:
    inv = spec["invoice"]
    title = "FACTURE" if inv["doc_type"] == "facture" else "DEVIS"
    out = [inv["supplier"], ADDRESSES[inv["supplier"]], "", f"{title} N° {inv['number']}",
           f"Date : {_fmt_date(date.fromisoformat(inv['issue_date']), layout)}"]
    if inv["due_date"]:
        out.append(f"Échéance : {_fmt_date(date.fromisoformat(inv['due_date']), layout)}")
    else:
        out.append("Devis valable 30 jours")
    out += ["", f"Client : {inv['customer']}", ADDRESSES[inv["customer"]], "", "Désignation | Qté | PU HT | Total HT"]
    for label, qty, price in spec["lines"]:
        total = money(qty * Decimal(price))
        out.append(f"{label} | {qty} | {_fmt_money(Decimal(price))} | {_fmt_money(total)}")
    out += ["", f"Total HT : {_fmt_money(Decimal(inv['amount_excl_tax']))}",
            f"TVA 20 % : {_fmt_money(Decimal(inv['vat_amount']))}",
            f"Total TTC : {_fmt_money(Decimal(inv['amount_incl_tax']))}"]
    return out


def render_pdf(spec: dict, path: Path, layout: int) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    x = 50 if layout == 0 else 70
    for i, line in enumerate(_text_lines(spec, layout)):
        pdf.setFont("Helvetica-Bold" if i in (0, 3) or line.startswith("Total TTC") else "Helvetica", 11)
        if line.startswith(("Total", "TVA")) and layout == 1:
            pdf.drawRightString(width - 60, y, line)
        else:
            pdf.drawString(x, y, line)
        y -= 18
    pdf.save()


def render_letter(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    lines = ["Transports Martin", "", "Objet : changement d'adresse de notre siège", "",
             "Madame, Monsieur,", "Nous vous informons que notre siège social déménage au 1er octobre 2026.",
             "Merci de mettre à jour vos coordonnées.", "", "Cordialement, la direction"]
    y = A4[1] - 60
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 18
    pdf.save()


def render_scan(spec: dict, path: Path) -> None:
    rng = random.Random(42)
    image = Image.new("L", (1240, 1754), color=245)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    y = 80
    for line in _text_lines(spec, 0):
        draw.text((90, y), line, fill=30, font=font)
        y += 40
    for _ in range(4000):
        draw.point((rng.randrange(1240), rng.randrange(1754)), fill=rng.randrange(120, 200))
    image = image.rotate(1.5, fillcolor=245).filter(ImageFilter.GaussianBlur(0.8))
    image.save(path)


def generate(out_dir: Path = DATASET_DIR) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = build_specs()
    for index, spec in enumerate(specs):
        path = out_dir / spec["file"]
        if spec.get("letter"):
            render_letter(path)
        elif path.suffix == ".png":
            render_scan(spec, path)
        else:
            render_pdf(spec, path, layout=index % 2)
    documents = [{k: v for k, v in s.items() if k in ("file", "expected_status", "expected_issues", "accept", "invoice")}
                 for s in specs]
    (out_dir / "expected.json").write_text(
        json.dumps({"today": TODAY.isoformat(), "documents": documents}, ensure_ascii=False, indent=2)
    )
    return specs


if __name__ == "__main__":
    generated = generate()
    print(f"{len(generated)} documents générés dans {DATASET_DIR}")
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_generate.py -v`
Expected : 4 passed

- [ ] **Step 5 : générer le jeu et vérifier visuellement**

Run : `uv run python -m evals.generate`
Expected : `20 documents générés dans .../evals/dataset`. Ouvrir `evals/dataset/01_bureau_plus.pdf`, `07_dupont_scan.png` et `14_courrier.pdf` pour vérifier qu'ils sont lisibles et crédibles.

- [ ] **Step 6 : commit**

```bash
git add -A
git commit -m "feat: jeu d'évaluation de 20 documents fictifs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11 : scoring et lancement des evals

**Files :**
- Create : `evals/scoring.py`, `evals/run.py`, `evals/results/.gitkeep`
- Test : `tests/test_scoring.py`

**Interfaces :**
- Consumes : `InvoiceAgent`, `AgentResult` (Task 7) ; `Invoice` (Task 1) ; `InvoiceRepository`, `connect` (Task 2) ; format `expected.json` (Task 10)
- Produces :
  - `FIELDS: list[str]`
  - `field_matches(field: str, expected, actual) -> bool`
  - `DocOutcome(file, expected: dict, status: str, issues: set[str], invoice: Invoice | None, cost_usd: float | None, seconds: float)` (dataclass)
  - `summarize(outcomes: list[DocOutcome]) -> dict` avec les clés `field_accuracy` (dict par champ), `overall_field_accuracy`, `detection_precision`, `detection_recall`, `verdict_accuracy`, `mean_cost_usd`, `mean_seconds`, `documents`
  - `to_markdown(model: str, summary: dict) -> str`
  - CLI : `uv run python -m evals.run --model claude-sonnet-5`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_scoring.py` :

```python
import json

import pytest

from evals.scoring import DocOutcome, field_matches, summarize, to_markdown
from tests.factories import make_invoice

EXPECTED_INVOICE = json.loads(
    make_invoice().model_dump_json(include={"doc_type", "direction", "supplier", "customer", "number", "issue_date",
                                            "due_date", "amount_excl_tax", "vat_amount", "amount_incl_tax"})
)


def outcome(**kw) -> DocOutcome:
    base = dict(file="f.pdf", expected={"expected_status": "ok", "expected_issues": [], "invoice": EXPECTED_INVOICE},
                status="ok", issues=set(), invoice=make_invoice(), cost_usd=0.01, seconds=2.0)
    base.update(kw)
    return DocOutcome(**base)


def test_field_matching_rules():
    assert field_matches("supplier", "Bureau Plus SARL", "  BUREAU plus sarl ")
    assert field_matches("amount_incl_tax", "120.00", 120.005)
    assert not field_matches("amount_incl_tax", "120.00", 120.02)
    assert field_matches("due_date", None, None)
    assert not field_matches("due_date", "2026-10-01", None)
    assert field_matches("issue_date", "2026-09-01", "2026-09-01")


def test_perfect_run():
    summary = summarize([outcome()])
    assert summary["overall_field_accuracy"] == 1.0
    assert summary["verdict_accuracy"] == 1.0
    assert summary["documents"] == 1


def test_missing_extraction_counts_as_all_fields_wrong():
    summary = summarize([outcome(invoice=None, status="a_revoir")])
    assert summary["overall_field_accuracy"] == 0.0
    assert summary["verdict_accuracy"] == 0.0


def test_detection_precision_and_recall():
    expected = {"expected_status": "anomalie", "expected_issues": ["DOUBLON", "ECHEANCE_DEPASSEE"], "invoice": EXPECTED_INVOICE}
    summary = summarize([outcome(expected=expected, status="anomalie", issues={"DOUBLON", "TOTAL_INCOHERENT"})])
    assert summary["detection_precision"] == pytest.approx(0.5)
    assert summary["detection_recall"] == pytest.approx(0.5)


def test_letter_is_excluded_from_field_accuracy():
    letter = outcome(expected={"expected_status": "a_revoir", "expected_issues": [], "invoice": None},
                     status="a_revoir", invoice=None)
    summary = summarize([outcome(), letter])
    assert summary["overall_field_accuracy"] == 1.0
    assert summary["verdict_accuracy"] == 1.0


def test_markdown_contains_headline_numbers():
    text = to_markdown("claude-sonnet-5", summarize([outcome()]))
    assert "claude-sonnet-5" in text
    assert "100,0 %" in text
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `uv run pytest tests/test_scoring.py -v`
Expected : FAIL avec `ModuleNotFoundError: No module named 'evals.scoring'`

- [ ] **Step 3 : implémenter**

`evals/scoring.py` :

```python
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
```

`evals/run.py` :

```python
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
```

```bash
mkdir -p evals/results && touch evals/results/.gitkeep
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `uv run pytest tests/test_scoring.py -v`
Expected : 6 passed

- [ ] **Step 5 : lancer toute la suite**

Run : `uv run pytest -v`
Expected : tous les tests passent

- [ ] **Step 6 : commit**

```bash
git add -A
git commit -m "feat: scoring et script d'évaluation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7 : premier run réel (nécessite la clé d'API, avec accord de l'utilisateur)**

Pré-requis : l'utilisateur a mis sa clé dans `.env`. Coût estimé : quelques centimes par modèle.

Run : `uv run python -m evals.run --model claude-sonnet-5` puis `uv run python -m evals.run --model claude-haiku-4-5`
Expected : deux fichiers `evals/results/claude-sonnet-5.md` et `evals/results/claude-haiku-4-5.md`. Comparer aux critères de la spec §11 (précision des champs d'au moins 90 %, rappel des anomalies de 100 % avec Sonnet). Si un critère n'est pas atteint, analyser les documents en échec avant de toucher au prompt.

```bash
git add evals/results
git commit -m "docs: résultats des évaluations Sonnet 5 et Haiku 4.5" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12 : README orienté portfolio

**Files :**
- Create : `README.md`

**Interfaces :**
- Consumes : résultats de `evals/results/*.md` (Task 11, Step 7), commandes des Tasks 1, 9, 10 et 11

- [ ] **Step 1 : écrire le README**

`README.md` (remplacer le contenu du tableau « Résultats » par celui des fichiers `evals/results/*.md` produits à la Task 11, Step 7 ; si les evals n'ont pas encore été lancées, garder la phrase indiquant la commande à exécuter) :

````markdown
# Agent factures

**Un agent IA qui lit vos factures, en extrait les données, repère les erreurs et prépare les relances clients, sous votre contrôle.**

Dans une PME, saisir et vérifier les factures prend plusieurs heures par semaine : recopier les montants, repérer les doublons, surveiller ce qu'il reste à payer aux fournisseurs et à encaisser auprès des clients. Cet agent fait le travail préparatoire, et un humain valide chaque pièce en quelques secondes.

<!-- Ajouter ici un GIF de démo : docs/demo.gif -->

## Ce que fait l'agent

1. **Lit** les factures et devis en PDF ou en image (y compris des scans).
2. **Extrait** l'émetteur, le destinataire, le sens (facture reçue d'un fournisseur ou émise vers un client), le numéro, les dates, les montants HT, TVA et TTC, et les lignes de détail.
3. **Vérifie** la cohérence des montants, les doublons, les montants inhabituels pour un fournisseur et les échéances dépassées.
4. **Explique** son verdict en langage clair : ✅ OK, ⚠️ anomalie ou ❓ à revoir.
5. **Attend votre validation** avant d'enregistrer quoi que ce soit.
6. **Prépare un brouillon de relance** pour les clients en retard de paiement, et signale les factures fournisseurs à régler. Rien n'est jamais envoyé automatiquement.

## Résultats mesurés

Évaluation sur 20 documents fictifs (mises en page variées, un scan, des doublons, des erreurs de TVA volontaires, des devis et un courrier hors sujet) :

Voir `evals/results/`. Pour reproduire : `uv run python -m evals.run --model claude-sonnet-5`.

## Démarrage rapide

```bash
git clone <url-du-dépôt> && cd agent-factures
cp .env.example .env        # puis renseigner ANTHROPIC_API_KEY (et COMPANY_NAME, le nom de votre entreprise)
uv sync
uv run streamlit run app/main.py
```

Des documents d'exemple se trouvent dans `evals/dataset/` : déposez-les dans l'interface ou copiez-les dans `inbox/`.

## Architecture

```
PDF / image ──► InvoiceAgent (boucle agentique) ──► verdict + extraction ──► validation humaine ──► SQLite
                     │  ▲
         tool_use    ▼  │  tool_result
                 ToolExecutor ──► check_amounts · check_due_date · find_duplicates · get_supplier_history
                                  (lecture seule)
```

| Module | Rôle |
|---|---|
| `agent_factures.extraction` | Modèles Pydantic (`Invoice`, `Verdict`, `Issue`) |
| `agent_factures.agent` | Boucle agentique écrite à la main sur l'API Messages de Claude, exécuteur d'outils, chargement des documents |
| `agent_factures.tools` | Vérifications déterministes et brouillon de relance |
| `agent_factures.storage` | SQLite, journal d'actions, exports CSV et Excel |
| `app/` | Interface Streamlit |
| `evals/` | Génération du jeu de test et mesure de la précision |

### Choix de conception

- **Boucle agentique manuelle plutôt qu'un framework** : environ 100 lignes lisibles, avec un contrôle total des garde-fous.
- **L'agent ne peut rien écrire** : il ne dispose que d'outils en lecture seule. L'enregistrement est une action humaine.
- **Contrôles déterministes en code, jugement par le LLM** : les calculs (TVA, doublons, seuils) sont faits par du code testé. Claude décide quoi vérifier et explique le résultat. Un verdict « OK » est automatiquement requalifié si un contrôle a détecté un problème.
- **Garde-fous** : 10 itérations maximum par document, une seule nouvelle tentative en cas d'extraction invalide, coût en tokens affiché pour chaque document.
- **Testé sans API** : la suite pytest utilise un client factice et ne consomme aucun crédit.

## Tests

```bash
uv run pytest
```

## Limites connues et feuille de route

- Pas encore de connexion à une boîte mail (Gmail ou IMAP).
- Pas de suivi des paiements : les totaux « à payer » et « à encaisser » portent sur toutes les factures enregistrées.
- Mono-utilisateur, sans authentification.
- Prochaines étapes : tri automatique des emails entrants, relances clients, option de modèle local pour les données sensibles.
````

- [ ] **Step 2 : vérifier les commandes du README**

Run : `uv sync && uv run pytest`
Expected : tous les tests passent.

- [ ] **Step 3 : commit**

```bash
git add README.md
git commit -m "docs: README orienté portfolio" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
