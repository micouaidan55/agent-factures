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
