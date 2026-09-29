"""bank_export: what may leave the bank, what may not, and the budget that caps it."""
from __future__ import annotations

import json

import pytest

from conftest import EXAMPLE_BANK
from resume_gate import bank_export
from resume_gate.bank_export import (
    apply_budget, assess, build_facts, export, self_check, variants,
)
from resume_gate.validator import validate_output


def by_id(items):
    return {i.eid: i for i in items}


# --- budget -----------------------------------------------------------------

def test_unknown_variant_raises_instead_of_uncapping(example_bank):
    with pytest.raises(ValueError, match="no bullet budget for variant 'quant'"):
        apply_budget([], "quant", example_bank)


def test_every_variant_in_the_bank_is_accepted(example_bank):
    for name in variants(example_bank):
        assert apply_budget([], name, example_bank) == ([], [])


def test_variant_lookup_ignores_case(example_bank):
    assert apply_budget([], "SWE", example_bank) == ([], [])


def test_over_budget_is_cut_with_a_reason_not_dropped(example_bank):
    example_bank["variants"]["swe"]["budget"]["R-ENG"] = 1
    items = assess(example_bank, "swe")
    kept, cut = apply_budget(items, "swe", example_bank)
    assert "EV-09" in {i.eid for i in kept}          # lead order beats the rest
    assert [i.eid for i in cut] == ["EV-10"]
    assert any("capped at 1" in r for r in cut[0].reasons)


# --- assess -----------------------------------------------------------------

def test_private_record_is_never_exported(example_bank):
    item = by_id(assess(example_bank, None))["EV-30"]
    assert not item.usable
    assert any("disclosure: private" in r for r in item.reasons)


def test_placeholder_metric_source_drops_the_metric(example_bank):
    item = by_id(assess(example_bank, None))["EV-10"]
    assert item.usable and not item.metric_ok


def test_record_with_unknown_role_is_blocked(example_bank):
    example_bank["evidence"][0]["role_id"] = "R-NOPE"
    assert not by_id(assess(example_bank, None))["EV-01"].usable


def test_merged_record_is_retired(example_bank):
    example_bank["evidence"][1]["merged_into"] = "EV-01"
    assert not by_id(assess(example_bank, None))["EV-02"].usable


def test_unfinished_record_saying_built_is_blocked(example_bank):
    example_bank["evidence"][0]["action"] = "Built the warehouse scanner dashboard."
    item = by_id(assess(example_bank, None))["EV-01"]
    assert not item.usable
    assert any("completed-tense" in r for r in item.reasons)


def test_variant_filter_says_out_of_scope_not_weak(example_bank):
    item = by_id(assess(example_bank, "swe"))["EV-04"]      # tagged FDE only
    assert any("out of scope for this variant, not weak evidence" in r
               for r in item.reasons)


# --- facts ------------------------------------------------------------------

def test_facts_forbid_unsourced_and_withheld_numbers(example_bank):
    facts = build_facts(example_bank, assess(example_bank, None))
    assert "30%" in facts["forbidden_phrases"]              # UNKNOWN source
    assert "15%" in facts["forbidden_phrases"]              # metric_withheld
    assert "wrote the backend" in facts["forbidden_phrases"]  # forbidden_claims
    assert ">500 orders per minute" in facts["allow_metrics"]


def test_self_check_catches_a_forbidden_phrase_in_the_cv():
    facts = {"forbidden_phrases": ["wrote the backend"]}
    cv = "- Wrote the backend for the platform.  <!-- EV-02 -->"
    assert self_check(cv, facts) == [("wrote the backend", "EV-02")]


# --- the whole pipeline -----------------------------------------------------

@pytest.mark.parametrize("variant", [None, "swe", "fde"])
def test_exported_cv_passes_the_validator(example_bank, variant):
    """The exporter's own output must satisfy the validator, provenance included."""
    cv_text, _facts, _report, violations = export(example_bank, variant)
    assert violations == []
    report = validate_output(cv_text, example_bank, expect_provenance=True)
    assert not report.findings, "\n".join(f"{f.rule} {f.message}" for f in report.findings)


def test_cli_writes_three_files(tmp_path):
    assert bank_export.main(["--bank", str(EXAMPLE_BANK), "--out", str(tmp_path),
                             "--variant", "fde"]) == 0
    assert (tmp_path / "cv.md").read_text(encoding="utf-8").startswith("# Jordan Sample")
    assert "forbidden_phrases" in json.loads(
        (tmp_path / "cv-facts.json").read_text(encoding="utf-8"))
    assert (tmp_path / "bank-export-report.md").exists()


def test_cli_dry_run_writes_nothing(tmp_path):
    assert bank_export.main(["--bank", str(EXAMPLE_BANK), "--out", str(tmp_path / "x"),
                             "--dry-run"]) == 0
    assert not (tmp_path / "x").exists()


def test_cli_unknown_variant_fails(tmp_path):
    assert bank_export.main(["--bank", str(EXAMPLE_BANK), "--out", str(tmp_path),
                             "--variant", "quant"]) == 1
