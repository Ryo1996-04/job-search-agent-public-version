"""Output validation: does every claim in a resume trace back to the evidence bank?

The bank (a YAML file you maintain by hand) is the source of truth. A generated or
hand-edited resume is checked against it before anyone reads it. Each rule has a
short code so a failure points at the rule it broke:

  FORBIDDEN   a phrase the bank has withdrawn appears in the document
  METRIC      a number that no sourced record supports
  V13         an organisation the bank never mentions (invented affiliation)
  R4          completed-tense verbs ("shipped") about unfinished work
  DISCLOSURE  a record marked private appears in the document
  V19         a number printed without the qualifiers that make it true
  V16         sole-ownership language the bank cannot support
  V17         filler that says nothing checkable (warning only)
  TAG         a provenance tag that would print on the page (warning only)
  V4 / R3     with --expect-provenance: every experience bullet cites real records,
              of the role it sits under, whose dates fit inside that role

Run:
    python -m job_agent.validator <document.md> [--bank path] [--expect-provenance] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .models import BANNED_COMPLETED_VERBS, INCOMPLETE_STATUSES, UNSOURCED_MARKERS

ERROR, WARN = "ERROR", "WARN"

# Phrases that name an organisation. Anything matching one of these shapes is
# checked against the bank; ordinary prose does not match, so this stays quiet
# unless a document actually names an employer or school.
ORG_SHAPE = re.compile(
    r"\b([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,5}\s+"
    r"(?:Inc\.?|Corp\.?|Corporation|Company|Co\.?,?\s*Ltd\.?|Ltd\.?|LLC|LLP|GmbH|"
    r"University|Institute|College|Laboratories|Labs|Technologies|Holdings))\b"
)

# Claims of sole ownership. Harmless when true, but a team project written up as a
# solo one is the easiest lie to tell and the hardest to defend in an interview.
EXCLUSIVE_PHRASES = [
    "single-handedly", "sole engineer", "sole developer", "entirely by myself",
    "i built the entire", "built the entire", "solely responsible",
    "led the team that", "managed a team of 50", "led a team of 50",
]

UNSUPPORTED_SUPERLATIVES = [
    "world-class", "best-in-class", "proven track record", "passionate",
    "results-driven", "self-starter", "thought leader", "guru", "ninja",
]


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    evidence: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, severity: str, message: str, evidence: str = "") -> None:
        self.findings.append(Finding(rule, severity, message, evidence))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    @property
    def blocked(self) -> bool:
        return bool(self.errors)


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _norm(text: str) -> str:
    """Compare names without punctuation or case noise."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def load_bank(path: Path | None = None) -> dict[str, Any]:
    with (path or paths.default_bank()).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def known_names(bank: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Every organisation and title the bank can support."""
    orgs, titles = set(), set()
    for role in bank.get("roles", []):
        orgs.add(_norm(role.get("employer", "")))
        titles.add(_norm(role.get("title", "")))
    for edu in bank.get("education", []):
        orgs.add(_norm(edu.get("institution", "")))
    # Third parties the bank names in its own claims are fair to mention.
    for rec in bank.get("evidence", []):
        blob = " ".join(
            _clean(rec.get(k)) for k in ("action", "outcome", "project", "notes")
        )
        for m in ORG_SHAPE.finditer(blob):
            orgs.add(_norm(m.group(1)))
    orgs.discard("")
    titles.discard("")
    return orgs, titles


def private_records(bank: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in bank.get("evidence", [])
            if str(r.get("disclosure", "public")) == "private"]


def incomplete_records(bank: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in bank.get("evidence", [])
            if str(r.get("status", "")) in INCOMPLETE_STATUSES]


def claim_text(doc: str) -> str:
    """Strip the parts of a document that are not claims about the candidate.

    A master resume often ends with a "§ Do not add these back" appendix listing
    every withdrawn claim verbatim. Scanning it flagged the prohibition list as if
    it were a claim. Markdown tables and blockquotes there are explanatory too.

    A rule that fires on its own documentation is a rule nobody will keep.
    """
    kept: list[str] = []
    for line in doc.splitlines():
        stripped = line.strip()
        # Everything from a "§" heading onwards is appendix: guardrails, notes,
        # instructions to the reader. Not resume content.
        if re.match(r"^#+\s*§", stripped):
            break
        if stripped.startswith("|"):       # markdown table row
            continue
        if stripped.startswith(">"):       # blockquote: usually an instruction
            continue
        kept.append(line)
    return "\n".join(kept)


# Headings under which a line starting with "- " is an experience claim and so
# needs provenance. Education, skills and certificates are attributes, not
# achievements, and carry no evidence_id - flagging them was a false positive.
PROVENANCE_SECTIONS = re.compile(
    r"(experience|teaching|instruction|projects?|employment)", re.I
)

# A summary spans roles, so it cannot sit under one `###` heading and R3 does not
# apply. It need not carry a comment, but any id it does cite must be real.
SUMMARY_SECTIONS = re.compile(r"(summary|profile)", re.I)

# A master resume may write provenance as `[EV-09 · SWE]`. Unlike an HTML comment,
# that form prints in the rendered PDF, and the provenance check does not read it.
VISIBLE_EV_TAG = re.compile(r"\[[^\]\n]*\bEV-\d+[^\]\n]*\]")

# Metric-shaped tokens a reader takes as a measured result:
# 35%, 3.1x, 3.1×, $1,200, USD 1,000, 12,000, 300+, >500.
# Bare integers and years are deliberately not checked: "4 threads" and "2021"
# would make every document fail.
DOC_METRIC = re.compile(
    r"(?<![\w.-])(?P<pre>[>~])?(?:"
    r"(?P<pct>\d+(?:\.\d+)?)\s?%"
    r"|(?P<mult>\d+(?:\.\d+)?)\s?[x×](?![\w×])"
    r"|(?:USD|US\$|NT\$|\$)\s?(?P<money>\d[\d,]*(?:\.\d+)?)"
    r"|(?P<thousands>\d{1,3}(?:,\d{3})+)(?![\d.])"
    r"|(?P<plus>\d+)\+"
    r"|(?(pre)(?P<gt>\d+)|(?!))"        # ">300", "~40": only with the prefix
    r")"
)


def _number_value(token: str) -> float:
    return float(token.replace(",", ""))


def allowed_metric_values(bank: dict[str, Any]) -> set[float]:
    """Numbers the bank vouches for: those in a record's `metric` whose source is real.

    A number in `metric_withheld`, in a private or merged record, or behind a
    placeholder source ("UNKNOWN", "VERIFY") is not vouched for, so it never lands here.
    """
    allowed: set[float] = set()
    for rec in bank.get("evidence", []):
        if rec.get("merged_into") or str(rec.get("disclosure", "public")) == "private":
            continue
        source = str(rec.get("metric_source") or "")
        if not source or any(m in source.upper() for m in UNSOURCED_MARKERS):
            continue
        for token in re.findall(r"\d[\d,]*(?:\.\d+)?", _clean(rec.get("metric"))):
            allowed.add(_number_value(token))
    return allowed


def role_aliases(bank: dict[str, Any]) -> dict[str, list[str]]:
    """Resumes spell titles out; banks abbreviate them.

    "### Chief Technology Officer" should match a bank title of "CTO", so a role may
    list `aliases:` in the bank. The bank's own title is always accepted too.
    """
    return {r.get("role_id"): list(r.get("aliases") or []) for r in bank.get("roles", [])}


def validate_output(doc: str, bank: dict[str, Any], *, expect_provenance: bool = False
                    ) -> Report:
    report = Report()
    doc = claim_text(doc)
    lower = doc.lower()
    orgs, titles = known_names(bank)

    # --- FORBIDDEN: withdrawn claims must never come back --------------------
    for phrase in bank.get("forbidden_claims") or []:
        phrase = str(phrase).strip()
        if phrase and phrase.lower() in lower:
            report.add(
                "FORBIDDEN", ERROR,
                f"contains a withdrawn claim: {phrase!r}",
                "The bank lists this under forbidden_claims. It was ruled out once; "
                "it does not come back through a rewrite.",
            )

    # --- METRIC: every number needs a sourced record behind it ---------------
    # Blocklisting the numbers you remember to withdraw is not enough. A number the
    # bank has never seen (say, an invented "35%") must fail too.
    allowed = allowed_metric_values(bank)
    seen: set[str] = set()
    for m in DOC_METRIC.finditer(doc):
        token = next(v for k, v in m.groupdict().items() if k != "pre" and v)
        if _number_value(token) in allowed or m.group(0) in seen:
            continue
        seen.add(m.group(0))
        report.add(
            "METRIC", ERROR,
            f"{m.group(0).strip()!r} is not a metric any sourced record supports",
            "Add it to a record's `metric` with a real `metric_source`, or remove it. "
            "No source, no number.",
        )

    # --- V13: affiliation and titles must come from the bank -----------------
    for m in ORG_SHAPE.finditer(doc):
        phrase = m.group(1).strip()
        norm = _norm(phrase)
        if not norm:
            continue
        # A substring match either way: "Example State University" in the bank
        # should accept the same name written with a campus suffix.
        if any(norm in k or k in norm for k in orgs):
            continue
        report.add(
            "V13", ERROR,
            f"names an organisation that is not in the evidence bank: {phrase!r}",
            "Invented affiliation. If this is real, add it to the bank first - "
            "the bank is the source of truth.",
        )

    # --- R4: unreleased work may not use completed-tense verbs ---------------
    for rec in incomplete_records(bank):
        project = _clean(rec.get("project"))
        if not project:
            continue
        # Match the verb near the project name rather than anywhere in the doc,
        # so "shipped" about a different record does not fire here.
        for verb in sorted(BANNED_COMPLETED_VERBS):
            pattern = re.compile(
                rf"\b{verb}\b[^.]{{0,80}}{re.escape(project[:40])}", re.I | re.S
            )
            if pattern.search(doc):
                report.add(
                    "R4", ERROR,
                    f"{rec.get('evidence_id')} is status={rec.get('status')} but the "
                    f"document says {verb!r} about {project[:50]!r}",
                    "That work did not reach release. Use architected / designed / "
                    "validated / completed and handed off.",
                )
                break

    # --- DISCLOSURE: nothing private may be named ----------------------------
    for rec in private_records(bank):
        action_head = _clean(rec.get("action"))[:40].lower()
        if action_head and action_head in lower:
            report.add(
                "DISCLOSURE", ERROR,
                f"{rec.get('evidence_id')} is disclosure: private and must never "
                f"appear in a document",
                _clean(rec.get("disclosure_note"))[:160],
            )

    # --- V19: a cleared number must travel with its definition ---------------
    # Some numbers are true only as stated. "12,000 sign-ups since 2018" is
    # cumulative reach; printed bare it reads as active merchants, which is a different
    # and much larger claim. METRIC checks whether a number is allowed, not whether
    # it is qualified, so this rule is driven by `metric_requires_qualifier`.
    #
    # Three ways an earlier version of this rule was silently dead:
    #   - the number pattern had no decimals, so "3.1" became "3" and "1", and
    #     single digits are dropped as noise - nothing was ever searched for;
    #   - one qualifier out of five was accepted; now ALL are required;
    #   - the sentence window split on the "." inside "3.1".
    # Qualifiers must sit in the claim itself. A year in the role's date line does
    # not count: "2024 - present" would otherwise qualify every figure under it.
    for rec in bank.get("evidence", []):
        # YAML reads unquoted 50 and 2026 as ints.
        required = [str(q) for q in rec.get("metric_requires_qualifier") or []]
        if not required:
            continue
        metric = _clean(rec.get("metric"))
        # A number that is itself a listed qualifier is not a figure. Checking the
        # scope years of "since 2018 (2024)" as figures made every "Oct 2018" date
        # line demand "2024".
        figures = [n for n in _metric_numbers(metric) if n not in required]
        for number in figures:
            for m in _number_pattern(number).finditer(doc):
                claim = _claim_window(doc, m.start(), m.end()).lower()
                missing = [q for q in required if q.lower() not in claim]
                if missing:
                    report.add(
                        "V19", ERROR,
                        f"{rec.get('evidence_id')}: {number!r} appears without its "
                        f"required qualifier(s) - missing {', '.join(missing)} "
                        f"(all of {', '.join(required)} are required)",
                        f"Bare, it reads as a different claim. Required wording is in "
                        f"the record's metric: {metric!r}",
                    )
                    break

    # --- V16: sole-ownership language ---------------------------------------
    for phrase in EXCLUSIVE_PHRASES:
        if phrase in lower:
            report.add(
                "V16", ERROR,
                f"claims sole ownership: {phrase!r}",
                "The bank does not support it. Claim what you executed, not "
                "leadership you did not hold.",
            )

    # --- V17: unsupported filler (advisory) ---------------------------------
    for phrase in UNSUPPORTED_SUPERLATIVES:
        if phrase in lower:
            report.add("V17", WARN, f"unsupported filler: {phrase!r}",
                       "Says nothing a reader can check.")

    # --- TAG: provenance written where a reader will see it -----------------
    for line in re.sub(r"<!--.*?-->", "", doc, flags=re.S).splitlines():
        for m in VISIBLE_EV_TAG.finditer(line):
            report.add(
                "TAG", WARN,
                f"visible evidence tag {m.group()!r} will render in the document",
                "Write it as <!-- EV-xx --> - the only form --expect-provenance "
                "reads, and invisible once rendered.",
            )

    # --- V4: every experience bullet traceable ------------------------------
    # Scoped to experience-style sections. Education, Skills and Certifications
    # are attributes rather than achievements: they cannot carry an evidence_id.
    if expect_provenance:
        report.findings.extend(_check_provenance(doc, bank))
    return report


# A "." ends a sentence only when whitespace follows it, so the point in 3.1x
# does not. Nor does an abbreviation: "orjson vs. json" must not cut the
# verb out of its own claim.
_SENTENCE_END = re.compile(r"\.(?=\s|$)")
_ABBREVIATIONS = {"vs", "e.g", "i.e", "cf", "approx", "incl"}
# A claim also ends where its bullet does: the next bullet, a blank line or a
# heading. Without this, an unpunctuated bullet borrowed its neighbour's words.
_BLOCK_BREAK = re.compile(r"\n[ \t]*(?:[-*+][ \t]|#|\n)")


def _metric_numbers(metric: str) -> list[str]:
    """Numbers in a record's metric that V19 must find qualified in the document.

    "3.1x ...; 2.2x end-to-end" -> ["3.1", "2.2"]; "12,000 ... (2024)"
    -> ["12,000", "2024"]. A lone digit is dropped: "4" would match everywhere.
    """
    tokens = re.findall(r"\d[\d,]*(?:\.\d+)?", metric)
    return [t for t in tokens if sum(c.isdigit() for c in t) > 1]


def _number_pattern(number: str) -> re.Pattern[str]:
    """Match the number as a whole number, whatever follows it (x, ×, a space).

    "12,000" must not match inside "112,000". A decimal also matches the unrounded
    figure - a bank that rounds 3.14x to 3.1x means "3.14×" bare is the same claim.
    """
    tail = r"\d*" if "." in number else ""
    # Nor inside an identifier: "EV-20" and "Q20" are ids, not the figure 20. A
    # record with a camp size of 20-30 once made every document carrying a visible
    # [EV-20] tag fail this rule.
    return re.compile(rf"(?<!\d)(?<!\d[.,])(?<![A-Za-z]-)(?<![A-Za-z])"
                      rf"{re.escape(number)}{tail}(?![.,]?\d)")


def _boundaries(doc: str) -> list[tuple[int, int]]:
    """(start, end) of every sentence end and bullet break in the document."""
    spans = [m.span() for m in _BLOCK_BREAK.finditer(doc)]
    for m in _SENTENCE_END.finditer(doc):
        word = re.search(r"[\w.]*$", doc[max(0, m.start() - 12):m.start()]).group()
        if word.lower() not in _ABBREVIATIONS:
            spans.append(m.span())
    return spans


def _claim_window(doc: str, start: int, end: int) -> str:
    """The sentence around doc[start:end], never crossing into another bullet."""
    spans = _boundaries(doc)
    left = max((e for s, e in spans if e <= start), default=0)
    right = min((s for s, e in spans if s >= end), default=len(doc))
    return doc[left:right]


def _heading_role(heading: str, bank: dict[str, Any]) -> str | None:
    """The role_id a `###` heading names, or None if it names no role in the bank.

    A prefix match, because headings carry more than the title:
    "Head of Engineering - Northwind Traders Co., Ltd.".
    """
    norm = _norm(heading.lstrip("#"))
    aliases = role_aliases(bank)
    for role in bank.get("roles", []):
        role_id = role.get("role_id")
        names = [role.get("title", "")] + aliases.get(role_id, [])
        if any(_norm(n) and norm.startswith(_norm(n)) for n in names):
            return role_id
    return None


_PERIOD_PART = r"(\d{4})(?:-(\d{2}))?"
_PERIOD_RE = re.compile(
    rf"^\s*{_PERIOD_PART}(?:\s+to\s+(?:{_PERIOD_PART}|(present)))?\s*$", re.I)

YearMonth = tuple[int, "int | None"]


def _parse_period(text: Any) -> tuple[YearMonth, YearMonth | None] | None:
    """"2021-11 to 2022-01", "2021 to 2025", "2026-09", "2026-09 to present".

    Returns (start, end); end is None for "present". A month of None means the
    record is only as precise as a year, and is compared at that precision - so
    "2021 to 2025" sits inside a role that ends 2025-06, where padding it to
    2025-12 would call a true record false. Anything else returns None: unread.
    """
    m = _PERIOD_RE.match(str(text or ""))
    if not m:
        return None
    y1, m1, y2, m2, present = m.groups()
    start: YearMonth = (int(y1), int(m1) if m1 else None)
    if present:
        return start, None
    if y2:
        return start, (int(y2), int(m2) if m2 else None)
    return start, start


def _earlier(a: YearMonth, b: YearMonth) -> bool:
    """a is strictly before b, at the coarser of the two precisions."""
    if a[1] is None or b[1] is None:
        return a[0] < b[0]
    return a < b


def _check_dates(ev: str, rec: dict[str, Any], roles: dict[str, Any], head: str
                 ) -> list[Finding]:
    """R3: a record's period must sit inside its own role's dates.

    This is the check the project was founded on: a hand-edited resume placed an
    award under a role that had already ended. A record with no period cannot be
    checked; that warns rather than passing silently.
    """
    owner = rec.get("role_id")
    role = roles.get(owner) or {}
    span = f"{role.get('start', '?')} to {role.get('end', '?')}"
    period = rec.get("period")
    if period in (None, ""):
        return [Finding(
            "R3", WARN,
            f"{ev} has no recorded period, so its dates were not checked against "
            f"{owner} ({span}): {head}",
            "Record the period in the bank.")]
    parsed = _parse_period(period)
    role_start = _parse_period(role.get("start"))
    ongoing = str(role.get("end", "")).lower() == "present"
    role_end = None if ongoing else _parse_period(role.get("end"))
    if parsed is None or role_start is None or (role_end is None and not ongoing):
        return [Finding(
            "R3", WARN,
            f"{ev} period {period!r} or its role's dates could not be read, so the "
            f"range was not checked: {head}",
            "Use YYYY-MM, YYYY, 'YYYY-MM to YYYY-MM' or '... to present'.")]
    start, end = parsed
    too_early = _earlier(start, role_start[0])
    too_late = (role_end is not None and
                (end is None or _earlier(role_end[1] or role_end[0], end)))
    if too_early or too_late:
        return [Finding(
            "R3", ERROR,
            f"{ev} period {period} falls outside its role {owner} ({span}): {head}",
            "Evidence may not escape its role's dates. Move the record to the role "
            "it happened in, or correct the period.")]
    return []


def _check_provenance(doc: str, bank: dict[str, Any]) -> list[Finding]:
    """V4, with the mistakes this rule made on its first real documents.

    1. A bullet spans several lines and the `<!-- EV-xx -->` comment usually sits on
       the last of them. Checking only the line that starts with "- " flagged every
       wrapped bullet as unsourced.
    2. Section scope was reset by ANY heading, so a `### Head of Engineering`
       sub-heading turned the check off for the whole role beneath it. The rule was
       silently examining almost nothing - worse than reporting a false error,
       because it looked like it was passing.
    3. It checked that a comment was present, not what it said. `<!-- EV-99 -->`
       passed. Now every id must be a record in the bank, that record must belong to
       the `###` role heading the bullet sits under (R3) and, if unfinished, must
       not be described in completed tense (R4).
    4. A document with no in-scope bullets (a Summary only) was checked for nothing
       and reported OK. Now that warns, and a Summary's cited ids are checked too.

    So: only top-level (`#`/`##`) headings change scope, and each bullet is read as
    a block that runs until the next bullet, blank line or heading.
    """
    findings: list[Finding] = []
    records = {r.get("evidence_id"): r for r in bank.get("evidence", [])}
    roles = {r.get("role_id"): r for r in bank.get("roles", [])}
    scope: str | None = None          # "experience", "summary", or None: unchecked
    role_heading = ""                 # text of the current ### heading, "" if none
    role_id: str | None = None        # the role that heading names, None if unknown
    block: list[str] = []
    checked = 0                       # experience bullets examined

    def flush() -> None:
        nonlocal checked
        if not block:
            return
        text = " ".join(block)
        head = f"{block[0][:70]!r}"
        comments = re.findall(r"<!--(.*?)-->", text)
        block.clear()
        summary = scope == "summary"
        if not summary:
            checked += 1
        if not comments:
            if summary:
                return
            findings.append(Finding(
                "V4", ERROR,
                f"experience bullet has no evidence_id: {head}",
                "Every bullet maps to at least one record. No evidence, no sentence.",
            ))
            return
        # "<!-- EV-02, EV-04 -->" cites two records.
        ids = [t for c in comments for t in re.split(r"[\s,]+", c) if t]
        if not ids:
            findings.append(Finding(
                "V4", ERROR, f"evidence comment cites no evidence_id: {head}",
                "Every bullet maps to at least one record. No evidence, no sentence.",
            ))
            return
        claim = re.sub(r"<!--.*?-->", "", text)
        for ev in ids:
            rec = records.get(ev)
            if rec is None:
                findings.append(Finding(
                    "V4", ERROR,
                    f"cites {ev!r}, which is not an evidence_id in the bank: {head}",
                    "A comment that points at nothing is not provenance. Use an id "
                    "from the bank.",
                ))
                continue
            owner = rec.get("role_id")
            findings.extend(_check_dates(ev, rec, roles, head))   # R3: dates
            if summary:
                pass                                  # spans roles: no R3
            elif not role_heading:
                findings.append(Finding(
                    "R3", WARN,
                    f"{ev} sits under no ### role heading, so its role "
                    f"({owner}) was not checked: {head}",
                    "Put the bullet under the heading of the role it belongs to.",
                ))
            elif role_id is None:
                findings.append(Finding(
                    "R3", ERROR,
                    f"{ev} sits under {role_heading!r}, which names no role in the "
                    f"bank: {head}",
                    "Role headings must match a role's title or alias. An unknown "
                    "heading is an unsupported title.",
                ))
            elif owner != role_id:
                findings.append(Finding(
                    "R3", ERROR,
                    f"{ev} belongs to {owner} but sits under {role_heading!r} "
                    f"({role_id}): {head}",
                    "Evidence may not leave its role. Move the bullet under its own "
                    "role heading.",
                ))
            status = str(rec.get("status", ""))
            if status in INCOMPLETE_STATUSES:
                used = [v for v in sorted(BANNED_COMPLETED_VERBS)
                        if re.search(rf"\b{v}\b", claim, re.I)]
                if used:
                    findings.append(Finding(
                        "R4", ERROR,
                        f"{ev} is status={status} but its bullet says "
                        f"{', '.join(used)}: {head}",
                        "That work did not reach release. Use architected / designed "
                        "/ validated. If the verb is about another record, give that "
                        "record its own bullet.",
                    ))

    for line in doc.splitlines():
        stripped = line.strip()
        if re.match(r"^#{1,2}\s", stripped):          # top-level section
            flush()
            scope = ("experience" if PROVENANCE_SECTIONS.search(stripped)
                     else "summary" if SUMMARY_SECTIONS.search(stripped) else None)
            role_heading, role_id = "", None
            continue
        if re.match(r"^###\s", stripped):             # role heading: same section
            flush()
            role_heading = stripped.lstrip("#").strip()
            role_id = _heading_role(role_heading, bank)
            continue
        if stripped.startswith("#"):                  # #### grouping: same role
            flush()
            continue
        if scope is None:
            continue
        if stripped.startswith("- "):
            flush()
            block.append(stripped)
        elif stripped and (block or scope == "summary"):
            block.append(stripped)                    # continuation, or summary prose
        elif not stripped:
            flush()
    flush()
    if not checked:
        findings.append(Finding(
            "V4", WARN,
            "--expect-provenance found no experience bullets, so no bullet was "
            "checked",
            "Only `- ` bullets under an Experience / Teaching / Instruction / "
            "Projects / Employment heading are checked. An OK here proves nothing.",
        ))
    return findings


def render(report: Report, target: Path) -> str:
    out = [f"job-agent validate - {target.name}", ""]
    if not report.findings:
        out.append("  no findings.")
    for f in report.findings:
        out.append(f"  {f.severity:<5} {f.rule:<11} {f.message}")
        if f.evidence:
            out.append(f"              -> {f.evidence}")
    out.append("")
    out.append(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s). "
               f"{'BLOCKED.' if report.blocked else 'OK.'}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("document", type=Path)
    ap.add_argument("--bank", type=Path, default=None,
                    help="evidence bank YAML (default: profiles/experience_bank.yaml, "
                         "else the fictional example)")
    ap.add_argument("--expect-provenance", action="store_true",
                    help="require an <!-- EV-xx --> comment on every experience "
                         "bullet, citing real records of the role it sits under")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    # Findings quote the document, which may not be ASCII; a cp1252 Windows
    # console raised UnicodeEncodeError on them.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    bank = load_bank(args.bank)
    doc = args.document.read_text(encoding="utf-8")
    report = validate_output(doc, bank, expect_provenance=args.expect_provenance)

    if args.json:
        print(json.dumps(
            {"blocked": report.blocked,
             "findings": [f.__dict__ for f in report.findings]},
            indent=2, ensure_ascii=False))
    else:
        print(render(report, args.document))
    return 1 if report.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
