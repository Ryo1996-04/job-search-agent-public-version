"""db: the schema the rest of the pipeline writes into."""
from __future__ import annotations

import sqlite3

import pytest

from job_agent import db


@pytest.fixture
def conn(tmp_path):
    path = db.init_db(tmp_path / "agent.db")
    c = db.connect(path, create=False)
    yield c
    c.close()


def test_init_creates_every_table_and_is_idempotent(tmp_path, conn):
    assert set(db.table_counts(conn)) == set(db.COUNTED_TABLES)
    assert all(n == 0 for n in db.table_counts(conn).values())
    db.init_db(tmp_path / "agent.db")                 # a second run changes nothing
    assert db.schema_version(conn) == db.SCHEMA_VERSION


def test_connect_without_create_refuses_a_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        db.connect(tmp_path / "missing.db", create=False)


def _resume(conn) -> int:
    conn.execute("INSERT INTO jobs (job_id, ats_type, native_id, company, title, url, "
                 "discovered_at, dedupe_key) VALUES ('lever:acme:1', 'lever', '1', 'Acme', "
                 "'Engineer', 'https://example.com/1', '2026-01-01', 'acme engineer')")
    cur = conn.execute("INSERT INTO tailored_resumes (job_id, variant, created_at) "
                       "VALUES ('lever:acme:1', 'swe', '2026-01-01')")
    return cur.lastrowid


def test_a_resume_without_provenance_is_an_orphan(conn):
    resume_id = _resume(conn)
    assert db.orphan_bullets(conn) == 1
    conn.execute("INSERT INTO roles (role_id, employer, title, start) "
                 "VALUES ('R-ENG', 'Northwind Traders Co., Ltd.', 'Software Engineer', '2017-10')")
    conn.execute("INSERT INTO evidence (evidence_id, role_id, action, status, confidence) "
                 "VALUES ('EV-09', 'R-ENG', 'Built a returns service.', 'shipped', 'high')")
    conn.execute("INSERT INTO bullet_provenance VALUES (?, 0, 'EV-09')", (resume_id,))
    assert db.orphan_bullets(conn) == 0


def test_provenance_cannot_cite_evidence_that_does_not_exist(conn):
    resume_id = _resume(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO bullet_provenance VALUES (?, 0, 'EV-99')", (resume_id,))
