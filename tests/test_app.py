from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

import app.main as app_main
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
