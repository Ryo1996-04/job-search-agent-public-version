"""Filesystem layout. Every other module asks here rather than building paths itself."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Repo root. Override with RESUME_GATE_ROOT (tests use it to work in a tmpdir)."""
    env = os.environ.get("RESUME_GATE_ROOT")
    if env:
        return Path(env).resolve()
    # src/resume_gate/paths.py -> src/resume_gate -> src -> root
    return Path(__file__).resolve().parents[2]


ROOT = project_root()

# Your real bank lives here and is gitignored. The repo ships a fictional one.
PROFILES_DIR = ROOT / "profiles"
EXPERIENCE_BANK = PROFILES_DIR / "experience_bank.yaml"
EXAMPLE_BANK = ROOT / "examples" / "experience_bank.example.yaml"


def default_bank() -> Path:
    """The real bank if you have one, otherwise the fictional example."""
    return EXPERIENCE_BANK if EXPERIENCE_BANK.exists() else EXAMPLE_BANK
