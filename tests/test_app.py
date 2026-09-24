from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

import agent_factures.web as app_main
from agent_factures.storage.db import connect
from agent_factures.storage.repository import InvoiceRepository
from tests.factories import make_invoice

# The installed streamlit version resolves AppTest.from_file's relative paths
# against the calling file's directory, not the process cwd, so we pass an
# absolute path to the app entrypoint.
APP_PATH = str(Path(__file__).resolve().parent.parent / "app" / "main.py")


def test_app_starts_on_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_FACTURES_DB", str(tmp_path / "empty.db"))
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Agent factures"


def test_dashboard_shows_stored_invoices(tmp_path, monkeypatch):
    db_path = tmp_path / "seeded.db"
    InvoiceRepository(connect(str(db_path))).add(make_invoice(), "a.pdf")
    monkeypatch.setenv("AGENT_FACTURES_DB", str(db_path))
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.switch_page("app_pages/tableau_de_bord.py").run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["À payer (fournisseurs, TTC)"] == "120,00 €"
    assert metrics["À encaisser (clients, TTC)"] == "0,00 €"


def test_processing_inbox_without_api_key_shows_error_without_crashing(tmp_path, monkeypatch):
    # load_dotenv() never overrides an existing environment variable, so setting it to an
    # empty string (rather than deleting it) keeps the test true even when a repo-root .env
    # defines ANTHROPIC_API_KEY — the app treats an empty value as "missing".
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("AGENT_FACTURES_DB", str(tmp_path / "app.db"))
    monkeypatch.chdir(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "facture.pdf").write_bytes(b"%PDF-1.4 fake content")

    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    process_button = next(b for b in at.button if b.label == "Traiter le dossier inbox/")
    at = process_button.click().run()

    assert not at.exception
    assert any("Clé d'API" in e.value for e in at.error)
    assert not at.session_state.get("pending")
    # Nothing was actually processed, so the file must stay in the inbox (not archived).
    assert (inbox / "facture.pdf").exists()


def test_stored_upload_path_disambiguates_same_name_and_prevents_traversal():
    now = datetime(2026, 9, 24, 10, 30, 0, 123456)
    first = app_main.stored_upload_path("f.pdf", now)
    second = app_main.stored_upload_path("f.pdf", now.replace(microsecond=654321))
    assert first != second
    assert first.parent == app_main.UPLOAD_DIR
    assert second.parent == app_main.UPLOAD_DIR

    traversal = app_main.stored_upload_path("../../x.pdf", now)
    assert traversal.parent == app_main.UPLOAD_DIR
    assert ".." not in traversal.parts


def test_archive_inbox_file_moves_into_traites_subfolder(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    original = inbox / "facture.pdf"
    original.write_bytes(b"contenu")

    destination = app_main.archive_inbox_file(original)

    assert not original.exists()
    assert destination == inbox / "traites" / "facture.pdf"
    assert destination.read_bytes() == b"contenu"


def test_archiving_inbox_updates_pending_paths(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    original = inbox / "facture.pdf"
    original.write_bytes(b"contenu")
    result = object()
    pending = {"facture.pdf": (original, result)}

    app_main.archive_processed_inbox([original], pending)

    archived = inbox / "traites" / "facture.pdf"
    assert archived.exists()
    assert pending["facture.pdf"] == (archived, result)


def _result_with(invoice, issues):
    from agent_factures.agent.loop import AgentResult
    from agent_factures.extraction.models import Status, Verdict

    return AgentResult(
        invoice=invoice, partial_extraction=None,
        verdict=Verdict(status=Status.ANOMALY, explanation="Montants incohérents."),
        issues=issues, trace=[], input_tokens=0, output_tokens=0, cost_usd=None,
    )


def test_rejecting_a_received_invoice_with_amount_error_drafts_a_correction_request():
    from agent_factures.extraction.models import Issue

    issue = Issue(code="TOTAL_INCOHERENT", message="HT + TVA = 125,00 € mais le TTC indiqué est 120,00 €.")
    draft, note = app_main.rejection_follow_up(_result_with(make_invoice(number="TN-902"), [issue]))
    assert note is None
    assert "TN-902" in draft and "facture rectificative" in draft


def test_rejecting_an_issued_invoice_with_amount_error_only_shows_a_note():
    from agent_factures.extraction.models import Issue

    issue = Issue(code="LIGNES_INCOHERENTES", message="Somme des lignes fausse.")
    draft, note = app_main.rejection_follow_up(_result_with(make_invoice(direction="emise"), [issue]))
    assert draft is None
    assert "réémettre" in note


def test_rejecting_without_amount_error_needs_no_follow_up():
    from agent_factures.extraction.models import Issue

    duplicate = Issue(code="DOUBLON", message="Déjà enregistrée.")
    assert app_main.rejection_follow_up(_result_with(make_invoice(), [duplicate])) == (None, None)
    assert app_main.rejection_follow_up(_result_with(None, [])) == (None, None)


def test_journal_pages_list_invoices_and_toggle_payment(tmp_path, monkeypatch):
    from datetime import date, timedelta

    db_path = tmp_path / "journal.db"
    repo = InvoiceRepository(connect(str(db_path)))
    today = date.today()
    repo.add(make_invoice(number="A-PAYER", due_date=today + timedelta(days=10)), "a.pdf")
    late_id = repo.add(make_invoice(number="EN-RETARD", due_date=today - timedelta(days=5)), "b.pdf")
    repo.add(make_invoice(number="CLIENT-1", direction="emise", due_date=today - timedelta(days=3)), "c.pdf")
    monkeypatch.setenv("AGENT_FACTURES_DB", str(db_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    at = AppTest.from_file(APP_PATH, default_timeout=30).run()

    def page_text(page: str) -> str:
        at.switch_page(page).run()
        assert not at.exception, page
        return " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)

    assert "A-PAYER" in page_text("app_pages/journal_a_payer.py")
    assert "EN-RETARD" in page_text("app_pages/journal_retard.py")
    assert "CLIENT-1" in page_text("app_pages/journal_clients.py")
    page_text("app_pages/journal_payees.py")
    assert any("Aucune facture payée" in info.value for info in at.info)

    at.switch_page("app_pages/journal_retard.py").run()
    next(b for b in at.button if b.key == f"paid-{late_id}").click().run()
    assert not at.exception
    assert InvoiceRepository(connect(str(db_path))).get(late_id).paid_at == today

    assert "EN-RETARD" not in page_text("app_pages/journal_retard.py")
    assert "EN-RETARD" in page_text("app_pages/journal_payees.py")
    next(b for b in at.button if b.key == f"unpaid-{late_id}").click().run()
    assert not at.exception
    assert InvoiceRepository(connect(str(db_path))).get(late_id).paid_at is None

    at.switch_page("app_pages/journal_historique.py").run()
    assert not at.exception
    assert len(at.dataframe) == 1


def test_display_name_hides_the_upload_timestamp():
    stored = app_main.stored_upload_path("08_technet_tva.pdf", datetime(2026, 9, 24, 20, 4, 44, 286400))
    assert app_main.display_name(stored.name) == "08_technet_tva.pdf"
    assert app_main.display_name("facture.pdf") == "facture.pdf"
    assert app_main.display_name("2026_budget.pdf") == "2026_budget.pdf"
