"""Regression suite for the validator.

Each fixture is a plausible resume that breaks exactly one rule, plus clean
controls that must pass. The suite asserts the verdict, and for a block also the
reason: a block for the wrong reason is a coincidence, not a working rule.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from conftest import EDGE_BANK, EXAMPLE_BANK, FIXTURES, load
from resume_gate import validator
from resume_gate.validator import (
    DOC_METRIC, _claim_window, _number_pattern, _parse_period, claim_text,
    validate_output,
)

BLOCK, PASS, WARN = "block", "pass", "warn"


@dataclass
class Case:
    fixture: str
    verdict: str              # block | pass | warn
    because: str              # text the finding must contain
    why: str                  # the real-world error this prevents
    provenance: bool = False  # run with --expect-provenance
    edge: bool = False        # use the edge-case bank instead of the example


CASES = [
    Case("01-forbidden-claim.md", BLOCK, "withdrawn claim: 'wrote the backend'",
         "A claim that was ruled out once must not come back through a rewrite."),
    Case("02-unsourced-metric.md", BLOCK, "'~30%' is not a metric",
         "The speed-up was real; the number was never measured."),
    Case("03-invented-metric.md", BLOCK, "'35%' is not a metric",
         "THE IMPORTANT ONE: 35% appears nowhere in the bank. The gate must reject "
         "numbers it has never seen, not just the ones someone blocklisted."),
    Case("04-withheld-metric.md", BLOCK, "'~15%' is not a metric",
         "A withheld number sits in the same record as a cleared one. Clearing the "
         "record must not clear both."),
    Case("05-clean.md", PASS, "",
         "Control: only sourced metrics. A gate that blocks everything is not a gate."),
    Case("06-filler-warn.md", WARN, "proven track record",
         "Filler is bad writing, not a false claim: flag it, do not block it."),
    Case("07-wrong-org.md", BLOCK, "Acme Robotics Corporation",
         "An employer the bank never mentions. Invented affiliation is the most "
         "serious class of resume error."),
    Case("08-prerelease-verb.md", BLOCK, "status=pre-release but the document says",
         "The dashboard never reached the warehouse floor, so 'built' and 'launched' "
         "are false about it."),
    Case("09-missing-qualifier.md", BLOCK, "required qualifier",
         "'40 sessions' bare reads as a total; the record says 40 a year."),
    Case("10-bare-speedup-x.md", BLOCK, "required qualifier",
         "3.1x is true only as a median of 50 runs, measured in 2026."),
    Case("11-bare-speedup-unicode.md", BLOCK, "required qualifier",
         "The same claim with the Unicode multiplication sign resumes actually use."),
    Case("12-qualified-speedup.md", PASS, "",
         "Control: all qualifiers present. 'vs.' must not end the sentence and cut "
         "the verb out of the claim."),
    Case("13-year-only-in-dateline.md", BLOCK, "missing 2026",
         "The year sits only in the role's date line, which is not part of the claim."),
    Case("14-nonexistent-id.md", BLOCK, "'EV-99', which is not an evidence_id",
         "A comment pointing at no record is a bullet with no evidence dressed up "
         "as one with evidence.", provenance=True),
    Case("15-multi-id-one-nonexistent.md", BLOCK, "'EV-99', which is not an evidence_id",
         "Two real ids must not vouch for a third that does not exist.",
         provenance=True),
    Case("16-wrong-role-heading.md", BLOCK, "EV-09 belongs to R-ENG",
         "A real record under the wrong role claims a title and dates it never had.",
         provenance=True),
    Case("17-valid-multi-id.md", PASS, "",
         "Control: several ids, each under its own role. Parsing the list must not "
         "break real copy.", provenance=True),
    Case("18-prerelease-verb-by-id.md", BLOCK, "status=pre-release but its bullet says built",
         "This bullet never names the project, so only the cited id can tie the "
         "verb to the unfinished record.", provenance=True),
    Case("19-summary-only.md", WARN, "found no experience bullets",
         "A clean OK on a document with nothing in scope reads as 'verified' when "
         "nothing was verified.", provenance=True),
    Case("20-summary-nonexistent-id.md", BLOCK, "'EV-99', which is not an evidence_id",
         "A summary need not cite, but what it cites must exist.", provenance=True),
    Case("21-visible-ev-tag.md", WARN, "visible evidence tag",
         "A `[EV-xx]` tag prints on the page a recruiter reads."),
    Case("22-private-record.md", BLOCK, "disclosure: private",
         "A record under NDA is interview preparation only."),
    Case("23-sole-ownership.md", BLOCK, "claims sole ownership",
         "Team work written up as solo work."),
    Case("24-date-outside-role.md", BLOCK, "falls outside its role",
         "A 2021 award under a role that ended 2020-05: the error this project was "
         "founded to stop.", provenance=True, edge=True),
    Case("25-no-period.md", WARN, "has no recorded period",
         "A record with no period cannot be checked. It must say so, not pass.",
         provenance=True, edge=True),
    Case("26-year-precision-inside.md", PASS, "",
         "'2021 to 2025' is inside a role that ends 2025-06.",
         provenance=True, edge=True),
    Case("27-id-is-not-a-number.md", PASS, "",
         "EV-20 is an identifier, not the figure 20.", provenance=True, edge=True),
    Case("28-year-qualifier-not-a-figure.md", PASS, "",
         "A year listed as a qualifier is not a figure: an 'Oct 2019' date line must "
         "not demand '2021'.", edge=True),
    Case("29-sign-ups-bare.md", BLOCK, "required qualifier",
         "Excluding the years from the figures must not stop the figure itself "
         "from needing them.", edge=True),
]


def verdict(report) -> str:
    if report.blocked:
        return BLOCK
    return WARN if report.warnings else PASS


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.fixture)
def test_gate_case(case: Case) -> None:
    bank = load(EDGE_BANK if case.edge else EXAMPLE_BANK)
    doc = (FIXTURES / case.fixture).read_text(encoding="utf-8")
    report = validate_output(doc, bank, expect_provenance=case.provenance)
    messages = "\n".join(f"{f.rule} {f.message}" for f in report.findings)

    assert verdict(report) == case.verdict, (
        f"{case.fixture}: expected {case.verdict}, got {verdict(report)}.\n"
        f"Why it matters: {case.why}\nFindings:\n{messages or '(none)'}")
    if case.because:
        assert case.because.lower() in messages.lower(), (
            f"{case.fixture}: right verdict, wrong reason - never mentioned "
            f"{case.because!r}.\nFindings:\n{messages}")


def test_every_fixture_has_a_case() -> None:
    on_disk = {p.name for p in FIXTURES.glob("*.md")}
    assert on_disk == {c.fixture for c in CASES}


# --- the helpers the rules depend on ----------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("2021-11 to 2022-01", ((2021, 11), (2022, 1))),
    ("2021 to 2025", ((2021, None), (2025, None))),
    ("2026-09", ((2026, 9), (2026, 9))),
    ("2026-09 to present", ((2026, 9), None)),
    ("sometime in 2021", None),
    (None, None),
])
def test_parse_period(text, expected) -> None:
    assert _parse_period(text) == expected


@pytest.mark.parametrize("number, text, hits", [
    ("12,000", "about 12,000 sign-ups", True),
    ("12,000", "about 112,000 sign-ups", False),   # inside a larger number
    ("20", "recorded as EV-20", False),               # an identifier
    ("20", "question Q20", False),
    ("3.1", "3.1x faster", True),
    ("3.1", "3.14× faster", True),                    # unrounded is the same claim
    ("3.1", "13.1x faster", False),
])
def test_number_pattern(number, text, hits) -> None:
    assert bool(_number_pattern(number).search(text)) is hits


@pytest.mark.parametrize("text, found", [
    ("cut latency by 35%", ["35%"]),
    ("3.1x and 2.2× faster", ["3.1x", "2.2×"]),
    ("won USD 1,000 and $1,500", ["USD 1,000", "$1,500"]),
    ("reached 12,000 merchants and 300+ cities", ["12,000", "300+"]),
    ("served >300 users, ~40 a year", [">300", "~40"]),
    ("at 640x480, 4 threads, in 2026, cited as EV-21", []),   # not results
])
def test_doc_metric_finds_result_shaped_numbers(text, found) -> None:
    assert [m.group(0) for m in DOC_METRIC.finditer(text)] == found


def test_claim_window_does_not_split_on_decimal_or_abbreviation() -> None:
    doc = "- orjson vs. json: 3.1x faster parsing in 2026.\n- Next bullet 2027."
    start = doc.index("3.1")
    window = _claim_window(doc, start, start + 3)
    assert "orjson" in window and "2026" in window and "2027" not in window


def test_appendix_after_section_sign_is_not_a_claim(example_bank) -> None:
    doc = ("# Jordan Sample\n## Experience\n- Migrated the platform API.\n"
           "## § Do not add these back\n- wrote the backend\n")
    assert "wrote the backend" not in claim_text(doc)
    assert not validate_output(doc, example_bank).blocked


def test_cli_exit_codes_and_json(tmp_path, capsys) -> None:
    bad = FIXTURES / "03-invented-metric.md"
    assert validator.main([str(bad), "--bank", str(EXAMPLE_BANK), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["blocked"] is True
    assert any(f["rule"] == "METRIC" for f in payload["findings"])

    good = FIXTURES / "05-clean.md"
    assert validator.main([str(good), "--bank", str(EXAMPLE_BANK)]) == 0
