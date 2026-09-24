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
    _normalize_stored_numbers(conn)
    return conn


def _normalize_stored_numbers(conn: sqlite3.Connection) -> None:
    """Migre les numéros enregistrés avant la normalisation (idempotent)."""
    conn.create_function("number_key", 1, number_key, deterministic=True)
    conn.execute("UPDATE invoices SET number = number_key(number) WHERE number != number_key(number)")
    conn.commit()


def supplier_key(name: str) -> str:
    return " ".join(name.casefold().split())


def number_key(number: str) -> str:
    """Numéro de pièce normalisé : « F-2026/118 » et « f2026 118 » désignent la même pièce."""
    return "".join(char for char in number.casefold() if char.isalnum())
