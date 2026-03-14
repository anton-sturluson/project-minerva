"""SQLite storage layer for JobWatch."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS companies (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    ats_type    TEXT NOT NULL,
    ats_board   TEXT NOT NULL,
    website     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL REFERENCES companies(id),
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    is_exhaustive   INTEGER NOT NULL DEFAULT 0,
    postings_found  INTEGER,
    postings_new    INTEGER,
    postings_closed INTEGER,
    postings_changed INTEGER,
    response_hash   TEXT,
    error_message   TEXT,
    UNIQUE(company_id, started_at)
);

CREATE TABLE IF NOT EXISTS postings (
    id              TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL REFERENCES companies(id),
    ats_job_id      TEXT NOT NULL,
    title           TEXT NOT NULL,
    department_raw  TEXT,
    location        TEXT,
    work_mode       TEXT,
    employment_type TEXT,
    description     TEXT,
    content_hash    TEXT,
    url             TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    closed_at       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, ats_job_id)
);

CREATE TABLE IF NOT EXISTS classifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id          TEXT NOT NULL REFERENCES postings(id),
    justification       TEXT NOT NULL,
    department          TEXT NOT NULL,
    role_type           TEXT NOT NULL,
    seniority           TEXT NOT NULL,
    confidence          REAL,
    model               TEXT NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    is_current          INTEGER NOT NULL DEFAULT 1,
    classified_at       TEXT NOT NULL DEFAULT (datetime('now')),
    triggered_by        TEXT NOT NULL DEFAULT 'new_posting'
);

CREATE INDEX IF NOT EXISTS idx_classifications_current
    ON classifications(posting_id, is_current) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL REFERENCES companies(id),
    crawl_run_id    INTEGER NOT NULL REFERENCES crawl_runs(id),
    crawl_date      TEXT NOT NULL,
    total_active    INTEGER NOT NULL,
    dept_counts     TEXT NOT NULL,
    role_type_counts TEXT NOT NULL,
    seniority_counts TEXT NOT NULL,
    new_postings    INTEGER NOT NULL,
    closed_postings INTEGER NOT NULL,
    UNIQUE(company_id, crawl_date)
);
"""


def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    description: list = cursor.description
    return {col[0]: row[idx] for idx, col in enumerate(description)}


class JobWatchDB:
    """SQLite storage backend for JobWatch."""

    def __init__(self, db_path: Path):
        self._db_path: Path = db_path
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        """Return cached connection, creating one if needed (WAL mode, FKs on)."""
        if self._conn is not None:
            return self._conn
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = _row_to_dict  # type: ignore[assignment]
        return self._conn

    def init_db(self):
        """Create all tables if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn: sqlite3.Connection = self._connect()
        conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------

    def ensure_company(
        self,
        company_id: str,
        name: str,
        ats_type: str,
        ats_board: str,
        website: str | None,
    ):
        """INSERT OR IGNORE a company row."""
        conn: sqlite3.Connection = self._connect()
        conn.execute(
            "INSERT OR IGNORE INTO companies (id, name, ats_type, ats_board, website) "
            "VALUES (?, ?, ?, ?, ?)",
            (company_id, name, ats_type, ats_board, website),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Crawl runs
    # ------------------------------------------------------------------

    def create_crawl_run(self, company_id: str, started_at: str) -> int:
        """Insert a new crawl run and return its id."""
        conn: sqlite3.Connection = self._connect()
        cursor: sqlite3.Cursor = conn.execute(
            "INSERT INTO crawl_runs (company_id, started_at) VALUES (?, ?)",
            (company_id, started_at),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_crawl_run(
        self,
        run_id: int,
        *,
        status: str | None = None,
        is_exhaustive: bool | None = None,
        postings_found: int | None = None,
        postings_new: int | None = None,
        postings_closed: int | None = None,
        postings_changed: int | None = None,
        response_hash: str | None = None,
        error_message: str | None = None,
        finished_at: str | None = None,
    ):
        """Update only the non-None fields on a crawl run."""
        clauses: list[str] = []
        params: list = []
        field_map: dict[str, object] = {
            "status": status,
            "is_exhaustive": int(is_exhaustive) if is_exhaustive is not None else None,
            "postings_found": postings_found,
            "postings_new": postings_new,
            "postings_closed": postings_closed,
            "postings_changed": postings_changed,
            "response_hash": response_hash,
            "error_message": error_message,
            "finished_at": finished_at,
        }
        for col, val in field_map.items():
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        if not clauses:
            return
        params.append(run_id)
        conn: sqlite3.Connection = self._connect()
        conn.execute(
            f"UPDATE crawl_runs SET {', '.join(clauses)} WHERE id = ?", params
        )
        conn.commit()

    def get_recent_crawl_runs(self, limit: int = 20) -> list[dict]:
        """Return the most recent crawl runs."""
        conn: sqlite3.Connection = self._connect()
        cursor: sqlite3.Cursor = conn.execute(
            "SELECT * FROM crawl_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # Postings
    # ------------------------------------------------------------------

    def get_active_postings(self, company_id: str) -> dict[str, dict]:
        """Return {posting_id: row_dict} for all active postings of a company."""
        conn: sqlite3.Connection = self._connect()
        cursor: sqlite3.Cursor = conn.execute(
            "SELECT * FROM postings WHERE company_id = ? AND is_active = 1",
            (company_id,),
        )
        rows: list[dict] = cursor.fetchall()
        return {row["id"]: row for row in rows}

    def upsert_posting(
        self,
        company_id: str,
        posting: dict,
        content_hash: str,
        crawl_date: str,
    ) -> tuple[str, bool, bool]:
        """Insert or update a posting.

        Returns (posting_id, is_new, content_changed).
        """
        posting_id: str = f"{company_id}:{posting['ats_job_id']}"
        conn: sqlite3.Connection = self._connect()

        existing: dict | None = conn.execute(
            "SELECT id, content_hash FROM postings WHERE id = ?", (posting_id,)
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO postings "
                "(id, company_id, ats_job_id, title, department_raw, location, "
                "work_mode, employment_type, description, content_hash, url, "
                "first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    posting_id,
                    company_id,
                    posting["ats_job_id"],
                    posting["title"],
                    posting.get("department_raw"),
                    posting.get("location"),
                    posting.get("work_mode"),
                    posting.get("employment_type"),
                    posting.get("description"),
                    content_hash,
                    posting.get("url"),
                    crawl_date,
                    crawl_date,
                ),
            )
            conn.commit()
            return posting_id, True, False

        content_changed: bool = existing["content_hash"] != content_hash
        update_fields: str = (
            "last_seen = ?, is_active = 1, updated_at = datetime('now')"
        )
        params: list = [crawl_date]
        if content_changed:
            update_fields += (
                ", title = ?, department_raw = ?, location = ?, work_mode = ?, "
                "employment_type = ?, description = ?, content_hash = ?, url = ?"
            )
            params.extend([
                posting["title"],
                posting.get("department_raw"),
                posting.get("location"),
                posting.get("work_mode"),
                posting.get("employment_type"),
                posting.get("description"),
                content_hash,
                posting.get("url"),
            ])
        params.append(posting_id)
        conn.execute(
            f"UPDATE postings SET {update_fields} WHERE id = ?", params
        )
        conn.commit()
        return posting_id, False, content_changed

    def close_posting(self, posting_id: str, closed_at: str):
        """Mark a posting as inactive."""
        conn: sqlite3.Connection = self._connect()
        conn.execute(
            "UPDATE postings SET is_active = 0, closed_at = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (closed_at, posting_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Classifications
    # ------------------------------------------------------------------

    def insert_classification(
        self,
        posting_id: str,
        classification: dict,
        model: str,
        taxonomy_version: str,
        prompt_version: str,
        triggered_by: str,
    ):
        """Retire previous classifications and insert a new current one."""
        conn: sqlite3.Connection = self._connect()
        conn.execute(
            "UPDATE classifications SET is_current = 0 WHERE posting_id = ? AND is_current = 1",
            (posting_id,),
        )
        conn.execute(
            "INSERT INTO classifications "
            "(posting_id, justification, department, role_type, seniority, "
            "confidence, model, taxonomy_version, prompt_version, triggered_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                posting_id,
                classification["justification"],
                classification["department"],
                classification["role_type"],
                classification["seniority"],
                classification.get("confidence"),
                model,
                taxonomy_version,
                prompt_version,
                triggered_by,
            ),
        )
        conn.commit()

    def has_current_classification(
        self,
        posting_id: str,
        content_hash: str,
        taxonomy_version: str,
        prompt_version: str,
    ) -> bool:
        """Check if an up-to-date current classification already exists."""
        conn: sqlite3.Connection = self._connect()
        row: dict | None = conn.execute(
            "SELECT 1 FROM classifications c "
            "JOIN postings p ON p.id = c.posting_id "
            "WHERE c.posting_id = ? AND c.is_current = 1 "
            "AND p.content_hash = ? "
            "AND c.taxonomy_version = ? AND c.prompt_version = ?",
            (posting_id, content_hash, taxonomy_version, prompt_version),
        ).fetchone()
        return row is not None

    def get_low_confidence(self, threshold: float = 0.6) -> list[dict]:
        """Return current classifications below the confidence threshold."""
        conn: sqlite3.Connection = self._connect()
        cursor: sqlite3.Cursor = conn.execute(
            "SELECT c.*, p.title, p.company_id "
            "FROM classifications c "
            "JOIN postings p ON p.id = c.posting_id "
            "WHERE c.is_current = 1 AND c.confidence < ?",
            (threshold,),
        )
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def insert_snapshot(
        self,
        company_id: str,
        crawl_run_id: int,
        crawl_date: str,
        total_active: int,
        dept_counts: dict,
        role_type_counts: dict,
        seniority_counts: dict,
        new_postings: int,
        closed_postings: int,
    ):
        """Insert a point-in-time snapshot with JSON-encoded count dicts."""
        conn: sqlite3.Connection = self._connect()
        conn.execute(
            "INSERT INTO snapshots "
            "(company_id, crawl_run_id, crawl_date, total_active, dept_counts, "
            "role_type_counts, seniority_counts, new_postings, closed_postings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                crawl_run_id,
                crawl_date,
                total_active,
                json.dumps(dept_counts),
                json.dumps(role_type_counts),
                json.dumps(seniority_counts),
                new_postings,
                closed_postings,
            ),
        )
        conn.commit()

    def get_snapshots(self, company_id: str | None = None) -> list[dict]:
        """Return snapshots, optionally filtered by company. JSON-decodes count columns."""
        conn: sqlite3.Connection = self._connect()
        if company_id is not None:
            cursor: sqlite3.Cursor = conn.execute(
                "SELECT * FROM snapshots WHERE company_id = ? ORDER BY crawl_date",
                (company_id,),
            )
        else:
            cursor = conn.execute("SELECT * FROM snapshots ORDER BY crawl_date")
        rows: list[dict] = cursor.fetchall()
        for row in rows:
            row["dept_counts"] = json.loads(row["dept_counts"])
            row["role_type_counts"] = json.loads(row["role_type_counts"])
            row["seniority_counts"] = json.loads(row["seniority_counts"])
        return rows

    # ------------------------------------------------------------------
    # Analytics queries
    # ------------------------------------------------------------------

    def get_department_mix(self, company_id: str) -> list[dict]:
        """Current department counts for active postings."""
        conn: sqlite3.Connection = self._connect()
        cursor: sqlite3.Cursor = conn.execute(
            "SELECT c.department, COUNT(*) AS count "
            "FROM classifications c "
            "JOIN postings p ON p.id = c.posting_id "
            "WHERE p.company_id = ? AND p.is_active = 1 AND c.is_current = 1 "
            "GROUP BY c.department ORDER BY count DESC",
            (company_id,),
        )
        return cursor.fetchall()

    def get_role_type_counts(
        self,
        company_id: str | None = None,
        role_type: str | None = None,
    ) -> list[dict]:
        """Cross-company role type counts for active postings."""
        conn: sqlite3.Connection = self._connect()
        base: str = (
            "SELECT p.company_id, c.role_type, COUNT(*) AS count "
            "FROM classifications c "
            "JOIN postings p ON p.id = c.posting_id "
            "WHERE p.is_active = 1 AND c.is_current = 1"
        )
        params: list = []
        if company_id is not None:
            base += " AND p.company_id = ?"
            params.append(company_id)
        if role_type is not None:
            base += " AND c.role_type = ?"
            params.append(role_type)
        base += " GROUP BY p.company_id, c.role_type ORDER BY count DESC"
        cursor: sqlite3.Cursor = conn.execute(base, params)
        return cursor.fetchall()

    def get_all_active_postings_with_classifications(
        self, company_id: str | None = None
    ) -> list[dict]:
        """Join postings with their current classifications for dashboard use."""
        conn: sqlite3.Connection = self._connect()
        base: str = (
            "SELECT p.*, c.department, c.role_type, c.seniority, c.confidence, "
            "c.justification, c.model, c.taxonomy_version, c.prompt_version "
            "FROM postings p "
            "LEFT JOIN classifications c ON c.posting_id = p.id AND c.is_current = 1 "
            "WHERE p.is_active = 1"
        )
        params: list = []
        if company_id is not None:
            base += " AND p.company_id = ?"
            params.append(company_id)
        base += " ORDER BY p.last_seen DESC"
        cursor: sqlite3.Cursor = conn.execute(base, params)
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Close the database connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
