"""Filesystem layout. Every other module asks here rather than building paths itself."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Repo root. Override with JOB_AGENT_ROOT (tests use it to work in a tmpdir)."""
    env = os.environ.get("JOB_AGENT_ROOT")
    if env:
        return Path(env).resolve()
    # src/job_agent/paths.py -> src/job_agent -> src -> root
    return Path(__file__).resolve().parents[2]


ROOT = project_root()

# Your real bank lives here and is gitignored. The repo ships a fictional one.
PROFILES_DIR = ROOT / "profiles"
EXPERIENCE_BANK = PROFILES_DIR / "experience_bank.yaml"
EXAMPLE_BANK = ROOT / "examples" / "experience_bank.example.yaml"


def default_bank() -> Path:
    """The real bank if you have one, otherwise the fictional example."""
    return EXPERIENCE_BANK if EXPERIENCE_BANK.exists() else EXAMPLE_BANK

# The pipeline's SQLite database. Under data/, so it is never committed.
DB_PATH = ROOT / "data" / "agent.db"
