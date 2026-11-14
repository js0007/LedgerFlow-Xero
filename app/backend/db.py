"""SQLite database connection, DDL bootstrap, error model & UTC timestamps."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL_PATH = WORKSPACE_ROOT / "Accounting-SaaS-Blueprint" / "schemas" / "accounting_core_sqlite.sql"
AU_SEED_PATH = WORKSPACE_ROOT / "Accounting-SaaS-Blueprint" / "schemas" / "au-seed-data.json"


class ApiError(Exception):
    """Structured domain/HTTP error returned cleanly by Flask error handlers."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create schema from the canonical blueprint DDL."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    ddl = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    conn.executescript(ddl)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def atomic_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Execute block inside an immediate SQLite transaction."""
    in_tx = conn.in_transaction
    if not in_tx:
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        if not in_tx and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        if not in_tx and conn.in_transaction:
            conn.execute("COMMIT")


def compute_request_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_idempotency(
    conn: sqlite3.Connection, org_id: str, idempotency_key: str | None, payload: Any
) -> tuple[int, Any] | None:
    if not idempotency_key:
        return None
    req_hash = compute_request_hash(payload)
    row = conn.execute(
        "SELECT request_hash, response_status, response_body FROM idempotency_records WHERE org_id = ? AND idempotency_key = ?",
        (org_id, idempotency_key),
    ).fetchone()
    if row is None:
        return None
    if row["request_hash"] != req_hash:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with different request payload")
    return int(row["response_status"]), json.loads(row["response_body"])


def save_idempotency(
    conn: sqlite3.Connection,
    org_id: str,
    idempotency_key: str | None,
    payload: Any,
    status_code: int,
    body: Any,
) -> None:
    if not idempotency_key:
        return
    req_hash = compute_request_hash(payload)
    conn.execute(
        """
        INSERT OR IGNORE INTO idempotency_records (org_id, idempotency_key, request_hash, response_status, response_body, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (org_id, idempotency_key, req_hash, status_code, json.dumps(body, ensure_ascii=False), utc_now_iso()),
    )
