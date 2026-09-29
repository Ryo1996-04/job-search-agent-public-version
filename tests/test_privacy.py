"""No personal data in this repository - and proof that the check itself works.

The first half tests the scanner on strings built at runtime (a literal example
address or phone number in this file would make the repository scan fail). The
second half runs the scanner, and a few structural checks, on the repository.
"""
from __future__ import annotations

import re

import pytest

import privacy_scan as ps
from conftest import EDGE_BANK, EXAMPLE_BANK, FIXTURES, ROOT, load
from resume_gate.validator import ORG_SHAPE

AT, DOT = "@", "."


def kinds(text: str, denylist: set[str] | None = None) -> list[str]:
    return [f.kind for f in ps.scan_text(text, "x.md", denylist or set())]


# --- the scanner catches what it should ----------------------------------------

@pytest.mark.parametrize("address", [
    "someone" + AT + "gmail" + DOT + "com",
    "first.last" + AT + "school" + DOT + "edu",
    "a_b" + AT + "company" + DOT + "co",
])
def test_flags_real_looking_email(address):
    assert kinds(f"contact: {address}") == ["email address"]


@pytest.mark.parametrize("address", [
    "jordan" + AT + "example" + DOT + "com",
    "123+name" + AT + "users.noreply.github" + DOT + "com",
])
def test_allows_placeholder_and_noreply_email(address):
    assert kinds(address) == []


@pytest.mark.parametrize("number", [
    "555" + "-010-" + "0199",
    "(555) " + "010-" + "0199",
    "+1 555 " + "010 " + "0199",
    "0912" + "-345-" + "678",
    "+886 2 " + "1234 " + "5678",
])
def test_flags_phone_numbers(number):
    assert kinds(f"call {number} today") == ["phone number"]


@pytest.mark.parametrize("text", [
    "period: 2020-06 to 2025-06",
    "hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "version 1.2.3, 300 timed runs, 640x480",
])
def test_dates_versions_and_hashes_are_not_phones(text):
    assert kinds(text) == []


@pytest.mark.parametrize("path", [
    "C:" + "\\Users\\" + "someone\\project",
    "/" + "Users/" + "someone/project",
    "/" + "home/" + "someone/project",
])
def test_flags_home_directory_paths(path):
    assert kinds(f"see {path}") == ["home-directory path"]


def test_flags_linkedin_profile_and_unlisted_hosts():
    assert kinds("linkedin" + ".com/in/" + "someone-123") == ["LinkedIn profile URL"]
    assert kinds("https://" + "tracker.invalid/x") == ["link to unlisted host"]
    assert kinds("https://github.com/owner/repo and https://img.shields.io/x") == []


def test_denylist_matches_phrases_whatever_the_punctuation():
    denylist = {ps.hash_term(ps.normalize_term("Zebracorn Industries"))}
    for text in ("worked at Zebracorn Industries", "ZEBRACORN-INDUSTRIES",
                 "Zebracorn,  industries"):
        assert kinds(text, denylist) == ["denylisted term"], text
    assert kinds("zebracorn alone", denylist) == []


def test_denylist_matches_cjk_inside_a_longer_run():
    denylist = {ps.hash_term(ps.normalize_term("測試公司"))}
    assert kinds("這是測試公司的資料", denylist) == ["denylisted term"]
    assert kinds("這是測試的資料", denylist) == []


def test_denylist_finding_does_not_echo_the_term():
    denylist = {ps.hash_term("zebracorn")}
    [finding] = ps.scan_text("zebracorn", "x.md", denylist)
    assert "zebracorn" not in str(finding)


def test_normalize_term_rejects_what_the_scan_cannot_match():
    with pytest.raises(ValueError):
        ps.normalize_term("one two three four five")      # longer than MAX_WORDS
    with pytest.raises(ValueError):
        ps.normalize_term("測")                           # shorter than CJK_MIN


def test_plaintext_term_list_may_not_live_in_the_repo(tmp_path):
    inside = ROOT / "tools" / "terms-should-not-be-here.txt"
    with pytest.raises(ValueError, match="inside the repository"):
        ps.build_denylist(inside)
    outside = tmp_path / "terms.txt"
    outside.write_text("Zebracorn Industries  # a comment\n\n測試公司\n", encoding="utf-8")
    out = tmp_path / "denylist.sha256"
    assert ps.build_denylist(outside, out) == 2
    assert "Zebracorn" not in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel, private", [
    ("profiles/experience_bank.yaml", True),
    ("resumes/master/resume.md", True),
    ("applications/2026-01-01_acme/jd.md", True),
    ("data/notes.md", True),
    ("docs/resume.pdf", True),
    ("letter.docx", True),
    ("HANDOFF-2026-01-01.md", True),
    ("src/resume_gate/validator.py.bak-20260101", True),
    ("examples/experience_bank.example.yaml", False),
    ("src/resume_gate/validator.py", False),
])
def test_private_paths(rel, private):
    assert (ps.private_path(rel) is not None) is private


# --- the repository is clean ------------------------------------------------------

def test_denylist_is_hashes_only_and_not_empty():
    lines = [ln for ln in ps.DENYLIST.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#")]
    assert len(lines) >= 20, "the denylist looks truncated"
    assert all(re.fullmatch(r"[0-9a-f]{64}", ln) for ln in lines)


def test_repository_contains_no_personal_data():
    findings = ps.scan()
    assert not findings, "personal data found:\n" + "\n".join(map(str, findings))


def test_scan_covers_the_whole_repository():
    files = ps.repo_files()
    for expected in ("README.md", "src/resume_gate/validator.py",
                     "examples/experience_bank.example.yaml", "tests/test_privacy.py"):
        assert expected in files


def test_gitignore_keeps_private_data_out():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for pattern in ("profiles/", "resumes/", "applications/", "data/",
                    "*.pdf", "*.docx", ".env"):
        assert pattern in ignored


FICTIONAL = {
    "Jordan Sample", "Test Owner",
    "Northwind Traders Co., Ltd.", "Independent (self-directed)",
    "Example State University",
}


@pytest.mark.parametrize("bank_path", [EXAMPLE_BANK, EDGE_BANK], ids=lambda p: p.name)
def test_shipped_banks_name_only_fictional_people_and_places(bank_path):
    bank = load(bank_path)
    named = {bank["owner"]}
    named |= {r["employer"] for r in bank.get("roles", [])}
    named |= {e["institution"] for e in bank.get("education", [])}
    assert named <= FICTIONAL, f"not on the fictional list: {named - FICTIONAL}"


def test_fixtures_name_only_fictional_organisations():
    # Acme is the deliberately invented employer the V13 case must reject.
    allowed = {a.rstrip(".") for a in FICTIONAL | {"Acme Robotics Corporation"}}
    for doc in FIXTURES.glob("*.md"):
        text = doc.read_text(encoding="utf-8")
        owner = text.splitlines()[0].lstrip("# ").strip()
        assert owner in FICTIONAL, f"{doc.name}: owner {owner!r}"
        for m in ORG_SHAPE.finditer(text):
            assert m.group(1).rstrip(".") in allowed, f"{doc.name}: {m.group(1)!r}"
