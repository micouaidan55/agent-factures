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
