"""SQLite schema and connection handling.

The database is the source of truth for everything the agent produces.
`profiles/experience_bank.yaml` remains the source of truth for what is *true* —
the `roles` and `evidence` tables here are an imported mirror of it (Phase 3),
never edited directly.

The table that matters is `bullet_provenance`. A row in `tailored_resumes` without
matching provenance rows is a bug, not a state.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import paths

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---- imported from experience_bank.yaml (Phase 3), read-only mirror ----------
CREATE TABLE IF NOT EXISTS roles (
    role_id   TEXT PRIMARY KEY,
    employer  TEXT NOT NULL,
    title     TEXT NOT NULL,
    location  TEXT,
    start     TEXT NOT NULL,          -- YYYY-MM
    end       TEXT,                   -- YYYY-MM, or NULL for current
    industry  TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id   TEXT PRIMARY KEY,
    role_id       TEXT,               -- nullable: attribution may still be unresolved
    project       TEXT,
    action        TEXT NOT NULL,
    outcome       TEXT,
    period        TEXT,               -- optional narrower range inside the role
    metric        TEXT,
    metric_source TEXT,               -- NULL or contains UNKNOWN -> metric is unusable
    technologies  TEXT,               -- JSON array
    skills        TEXT,               -- JSON array
    status        TEXT NOT NULL,      -- shipped | pre-release | prototype | unknown
    confidence    TEXT NOT NULL,      -- high | medium | low
    job_families  TEXT,               -- JSON array
    notes         TEXT,
    FOREIGN KEY (role_id) REFERENCES roles(role_id)
);

CREATE TABLE IF NOT EXISTS open_questions (
    question_id TEXT PRIMARY KEY,
    severity    TEXT NOT NULL,        -- HIGH | MEDIUM | LOW
    issue       TEXT NOT NULL,
    action      TEXT,
    resolved_at TEXT
);

-- ---- discovery ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,   -- our id: "{ats}:{company}:{native_id}"
    ats_type      TEXT NOT NULL,      -- greenhouse | lever | ashby | smartrecruiters
    native_id     TEXT NOT NULL,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    remote        INTEGER,            -- 0/1/NULL
    url           TEXT NOT NULL,
    posted_at     TEXT,
    discovered_at TEXT NOT NULL,
    raw_jd        TEXT,
    content_hash  TEXT,               -- detects edited reposts
    dedupe_key    TEXT NOT NULL,      -- normalised (company, title, location)
    state         TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_jobs_state  ON jobs(state);

CREATE TABLE IF NOT EXISTS rejected_jobs (
    job_id      TEXT PRIMARY KEY,
    reason      TEXT NOT NULL,        -- eligibility failure, blacklist, duplicate, ...
    detail      TEXT,
    rejected_at TEXT NOT NULL
);

-- ---- scoring -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scores (
    score_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT NOT NULL,
    total          REAL NOT NULL,
    breakdown      TEXT NOT NULL,     -- JSON: component -> points
    covered        TEXT NOT NULL,     -- JSON: must-have -> evidence_id
    missing        TEXT NOT NULL,     -- JSON array of uncovered must-haves
    top_evidence   TEXT,              -- JSON array, max 3
    gaps           TEXT,              -- JSON array
    recommendation TEXT NOT NULL,     -- APPLY | REVIEW | SKIP
    weights_hash   TEXT NOT NULL,     -- scoring_weights.yaml hash: makes runs comparable
    scored_at      TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_job ON scores(job_id);

-- ---- tailoring + provenance --------------------------------------------------
CREATE TABLE IF NOT EXISTS tailored_resumes (
    resume_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       TEXT NOT NULL,
    variant      TEXT NOT NULL,       -- swe | tpm | tech_consulting | fde | gtm_engineer
    path         TEXT,
    created_at   TEXT NOT NULL,
    validated_at TEXT,                -- NULL means validate_bullets() has not passed
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS bullet_provenance (
    resume_id    INTEGER NOT NULL,
    bullet_index INTEGER NOT NULL,
    evidence_id  TEXT NOT NULL,
    PRIMARY KEY (resume_id, bullet_index, evidence_id),
    FOREIGN KEY (resume_id) REFERENCES tailored_resumes(resume_id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(evidence_id)
);

-- ---- applications and queues -------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    job_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,       -- prepared | submitted_by_user | abandoned
    package_path TEXT,
    prepared_at  TEXT,
    submitted_at TEXT,                -- set by the user via `outcome`; never by the agent
    notes        TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS review_queue (
    item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT,
    field       TEXT NOT NULL,
    kind        TEXT NOT NULL,        -- sensitive | ambiguous | gap
    question    TEXT NOT NULL,
    answer      TEXT,
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS blocker_queue (
    item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT,
    blocker     TEXT NOT NULL,        -- REQUIRES_HUMAN_ACTION reason
    detail      TEXT,
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);

-- ---- outcome loop ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL,
    status           TEXT NOT NULL,   -- rejected | screen | interview | offer
    responded_at     TEXT,
    days_to_response INTEGER,
    variant          TEXT,
    fit_score        REAL,
    recorded_at      TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
"""

# Every table, in the order the pipeline touches them.
COUNTED_TABLES = [
    "roles", "evidence", "open_questions",
    "jobs", "rejected_jobs", "scores",
    "tailored_resumes", "bullet_provenance",
    "applications", "review_queue", "blocker_queue", "outcomes",
]


def connect(db_path: Path | None = None, *, create: bool = True) -> sqlite3.Connection:
    path = db_path or paths.DB_PATH
    if not path.exists() and not create:
        raise FileNotFoundError(f"no database at {path} - call db.init_db() first")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> Path:
    """Create the schema. Idempotent."""
    path = db_path or paths.DB_PATH
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else None


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in COUNTED_TABLES:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()
        counts[t] = row["n"]
    return counts


def orphan_bullets(conn: sqlite3.Connection) -> int:
    """Bullets in a tailored resume with no provenance row. Must always be zero."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM tailored_resumes tr
        WHERE NOT EXISTS (
            SELECT 1 FROM bullet_provenance bp WHERE bp.resume_id = tr.resume_id
        )
        """
    ).fetchone()
    return row["n"]
