"""Shared vocabulary. Deliberately thin: the YAML bank is the real store.

Validation lives in validator.py, not here. A model that silently normalises bad
data is a model that hides the errors this project exists to catch.
"""
from __future__ import annotations

# Status values that may not be described with completed-tense verbs (rule R4).
INCOMPLETE_STATUSES = {"pre-release", "prototype", "unknown"}
BANNED_COMPLETED_VERBS = {
    "built", "launched", "shipped", "deployed", "delivered", "released",
}
# A metric_source containing any of these means the number is not usable.
UNSOURCED_MARKERS = ("UNKNOWN", "MUST FILL", "VERIFY")
