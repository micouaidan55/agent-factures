"""Éléments d'interface Streamlit partagés par les pages de app/ : dépôt, validation, tableau de bord et journal."""

import os
from datetime import date, datetime, timedelta
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
from agent_factures.storage.ledger import Ledger, build_ledger
from agent_factures.storage.repository import InvoiceRepository, StoredInvoice
from agent_factures.tools.formatting import euros
from agent_factures.tools.reminder import AMOUNT_ERROR_CODES, draft_correction_request, draft_reminder

load_dotenv()

COMPANY = os.environ.get("COMPANY_NAME", DEFAULT_COMPANY)
UPLOAD_DIR = Path("data/uploads")
INBOX_DIR = Path("inbox")
UPLOAD_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-%f"
ACCEPTED_TYPES = ["pdf", "png", "jpg", "jpeg"]
STATUS_LABELS = {Status.OK: "✅ OK", Status.ANOMALY: "⚠️ Anomalie", Status.NEEDS_REVIEW: "❓ À revoir"}


def stored_upload_path(name: str, now: datetime) -> Path:
    """Chemin de stockage d'un fichier déposé : horodaté pour ne jamais écraser un fichier
    déjà accepté, et réduit à son nom de base pour rester dans UPLOAD_DIR (pas de traversée)."""
    safe_name = Path(name).name or "fichier"
    return UPLOAD_DIR / f"{now.strftime(UPLOAD_TIMESTAMP_FORMAT)}_{safe_name}"


def archive_inbox_file(path: Path) -> Path:
    """Déplace un fichier de l'inbox traité vers inbox/traites/ pour ne pas le retraiter."""
    archive_dir = path.parent / "traites"
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / path.name
    path.rename(destination)
    return destination


def archive_processed_inbox(paths: list[Path], pending: dict) -> None:
    """Archive les fichiers traités et fait pointer les revues en attente vers leur nouvel emplacement."""
    for path in paths:
        archived = archive_inbox_file(path)
        if path.name in pending:
            pending[path.name] = (archived, pending[path.name][1])


def rejection_follow_up(result: AgentResult) -> tuple[str | None, str | None]:
    """Suite à donner au rejet d'une pièce : (brouillon de demande de rectification, message d'information)."""
    invoice = result.invoice
    if invoice is None or not any(issue.code in AMOUNT_ERROR_CODES for issue in result.issues):
        return None, None
    if invoice.direction is Direction.ISSUED:
        return None, "Facture émise avec une erreur de montant : corrige-la, puis pense à la réémettre à ton client."
    return draft_correction_request(invoice, result.issues), None


@st.cache_resource
def get_connection(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return connect(path)


def process_files(paths: list[Path], repo: InvoiceRepository, log: ActionLog, model: str) -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("Clé d'API Claude manquante : renseigne ANTHROPIC_API_KEY dans le fichier .env, puis relance l'application.")
        return False
    try:
        agent = InvoiceAgent(client=anthropic.Anthropic(), repo=repo, model=model, company=COMPANY)
    except anthropic.AnthropicError as exc:
        st.error(f"Client Claude indisponible : {exc}. Vérifie ANTHROPIC_API_KEY dans le fichier .env.")
        return False
    pending = st.session_state.setdefault("pending", {})
    for path in paths:
        with st.status(f"Analyse de {path.name}…", expanded=True) as box:
            try:
                result = agent.process(path)
            except Exception as exc:
                box.update(label=f"{path.name} : échec de l'analyse", state="error", expanded=True)
                st.error(f"Échec de l'analyse de {path.name} : {exc}")
                log.record(path.name, "erreur", {"message": str(exc)})
                continue
            for call in result.trace:
                box.write(f"🔧 `{call.name}` → {call.output[:200]}")
            box.update(label=f"{path.name} : {STATUS_LABELS[result.verdict.status]}", state="complete", expanded=False)
        log.record(
            path.name,
            "analyse",
            {
                "statut": result.verdict.status.value,
                "explication": result.verdict.explanation,
                "outils": [c.name for c in result.trace],
                "tokens": result.input_tokens + result.output_tokens,
                "cout_usd": result.cost_usd,
            },
        )
        pending[path.name] = (path, result)
    return True


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
        with st.expander("Détail des étapes de l'agent"):
            for call in result.trace:
                st.write(f"🔧 `{call.name}` → {call.output[:200]}")
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
            draft, note = rejection_follow_up(result)
            log.record(name, "rejete", {"brouillon_rectification": draft} if draft else None)
            if draft or note:
                st.session_state.setdefault("follow_ups", {})[name] = (draft, note)
            del st.session_state["pending"][name]
            st.rerun()


def render_process_tab(repo: InvoiceRepository, log: ActionLog, model: str) -> None:
    uploads = st.file_uploader("Dépose des factures ou devis", type=ACCEPTED_TYPES, accept_multiple_files=True)
    col1, col2 = st.columns(2)
    if col1.button("Analyser les fichiers déposés", disabled=not uploads):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        paths = []
        for upload in uploads:
            path = stored_upload_path(upload.name, datetime.now())
            path.write_bytes(upload.getvalue())
            paths.append(path)
        process_files(paths, repo, log, model)
    if col2.button("Traiter le dossier inbox/"):
        paths = sorted(p for p in INBOX_DIR.glob("*") if p.is_file() and not p.name.startswith("."))
        if paths:
            if process_files(paths, repo, log, model):
                archive_processed_inbox(paths, st.session_state.setdefault("pending", {}))
        else:
            st.info("Le dossier inbox/ est vide.")

    for name, (path, result) in list(st.session_state.get("pending", {}).items()):
        render_review(name, path, result, repo, log)

    follow_ups = st.session_state.get("follow_ups", {})
    for name, (draft, note) in list(follow_ups.items()):
        with st.container(border=True):
            st.subheader(f"{name} — rejetée")
            if draft:
                st.caption("Brouillon de demande de facture rectificative (rien n'est envoyé automatiquement) :")
                st.code(draft, language=None)
            if note:
                st.info(note)
            if st.button("Fermer", key=f"close-{name}"):
                del follow_ups[name]
                st.rerun()


def render_dashboard(repo: InvoiceRepository, today: date) -> None:
    stored = repo.list_all()
    ledger = build_ledger(repo, today)
    unpaid = ledger.to_pay + ledger.overdue + ledger.unpaid_customers
    to_pay = sum((s.invoice.amount_incl_tax for s in ledger.to_pay + ledger.overdue), Decimal("0"))
    to_collect = sum((s.invoice.amount_incl_tax for s in ledger.unpaid_customers), Decimal("0"))
    upcoming = [s for s in unpaid if s.invoice.due_date and today <= s.invoice.due_date <= today + timedelta(days=30)]
    late_suppliers = ledger.overdue
    late_customers = [s for s in ledger.unpaid_customers if Ledger.days_late(s, today) > 0]

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


def _render_unpaid(stored: StoredInvoice, repo: InvoiceRepository, log: ActionLog, today: date,
                   counterpart: str, with_reminder: bool = False) -> None:
    invoice = stored.invoice
    days_late = Ledger.days_late(stored, today)
    due = f"échéance {invoice.due_date:%d/%m/%Y}" if invoice.due_date else "sans échéance"
    late = f" — ⚠️ {days_late} jours de retard" if days_late else ""
    col_text, col_button = st.columns([4, 1])
    col_text.write(f"**{counterpart}** — n° {invoice.number} — {euros(invoice.amount_incl_tax)} — {due}{late}")
    if col_button.button("✓ Payée", help="Marquer comme payée", key=f"paid-{stored.id}"):
        repo.mark_paid(stored.id, today)
        log.record(Path(stored.source_file).name, "payee", {"id": stored.id, "numero": invoice.number})
        st.rerun()
    if with_reminder and days_late:
        with st.expander("Brouillon de relance"):
            st.code(draft_reminder(invoice, today), language=None)


UNPAID_SECTIONS = {
    "to_pay": ("Factures fournisseurs non payées, pas encore échues.", False),
    "overdue": ("Factures fournisseurs non payées dont l'échéance est passée, les plus anciennes d'abord.", False),
    "unpaid_customers": ("Factures émises que le client ne nous a pas encore payées.", True),
}
MODEL_KEY = "model"


def storage() -> tuple[InvoiceRepository, ActionLog]:
    conn = get_connection(os.environ.get("AGENT_FACTURES_DB", "data/factures.db"))
    return InvoiceRepository(conn), ActionLog(conn)


def render_model_selector() -> None:
    st.sidebar.selectbox("Modèle Claude", MODELS, index=MODELS.index(DEFAULT_MODEL), key=MODEL_KEY)


def render_process_page() -> None:
    repo, log = storage()
    render_process_tab(repo, log, st.session_state.get(MODEL_KEY, DEFAULT_MODEL))


def render_dashboard_page() -> None:
    repo, _ = storage()
    render_dashboard(repo, date.today())


def _summary(invoices: list[StoredInvoice]) -> str:
    total = sum((s.invoice.amount_incl_tax for s in invoices), Decimal("0"))
    return f"{len(invoices)} facture(s) — {euros(total)}"


def render_unpaid_page(kind: str) -> None:
    """Une des trois listes de factures non payées du journal (`kind` : clé de UNPAID_SECTIONS)."""
    caption, issued = UNPAID_SECTIONS[kind]
    repo, log = storage()
    today = date.today()
    invoices = getattr(build_ledger(repo, today), kind)
    st.caption(f"{caption} {_summary(invoices)}.")
    if not invoices:
        st.info("Aucune facture dans cette catégorie.")
    for stored in invoices:
        counterpart = (stored.invoice.customer or "Client") if issued else stored.invoice.supplier
        _render_unpaid(stored, repo, log, today, counterpart, with_reminder=issued)


def render_paid_page() -> None:
    repo, log = storage()
    paid = repo.list_paid()
    st.caption(f"Factures réglées, reçues et émises, la plus récemment payée en premier. {_summary(paid)}.")
    if not paid:
        st.info("Aucune facture payée pour l'instant.")
    for stored in paid:
        invoice = stored.invoice
        if invoice.direction is Direction.ISSUED:
            label = f"**{invoice.customer or 'Client'}** (client)"
        else:
            label = f"**{invoice.supplier}** (fournisseur)"
        col_text, col_button = st.columns([4, 1])
        col_text.write(f"{label} — n° {invoice.number} — {euros(invoice.amount_incl_tax)} — payée le {stored.paid_at:%d/%m/%Y}")
        if col_button.button("↩ Non payée", help="Annuler le paiement", key=f"unpaid-{stored.id}"):
            repo.mark_unpaid(stored.id)
            log.record(Path(stored.source_file).name, "paiement_annule", {"id": stored.id, "numero": invoice.number})
            st.rerun()


def render_history_page() -> None:
    _, log = storage()
    entries = log.list_recent(limit=200)
    if not entries:
        st.info("Le journal est vide.")
        return
    st.dataframe(pd.DataFrame([e.model_dump() for e in entries]), hide_index=True)
