"""Export the evidence bank into a derived CV, a fact file, and a report.

    experience_bank.yaml   (source of truth, hand-maintained)
          |
          +--> cv.md                  the derived CV. NEVER hand-edited.
          +--> cv-facts.json          allowed metrics and forbidden phrases, for any
          |                           downstream fact gate
          +--> bank-export-report.md  what was included, what was cut, and why

Every metric this exporter refuses to emit becomes a forbidden phrase, so a later
rewrite that reintroduces it fails loudly instead of slipping through.

Run:
    python -m resume_gate.bank_export --out build/ [--bank path] [--variant swe] [--dry-run]
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

CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

# Unsupported filler. Flag for a human rather than block: bad writing, not a lie.
WARN_PHRASES = [
    "proven track record", "passionate", "world-class", "best-in-class",
    "results-driven", "self-starter", "synergy", "thought leader",
]

# Matches a metric-shaped token: 40%, 12,000+, USD $1,500, 3.8/4.0, >100
METRIC_RE = re.compile(r"(?:USD\s*)?[$]?\d[\d,]*(?:\.\d+)?\s*(?:%|\+|/\d+(?:\.\d+)?)?")
# A number together with the word it qualifies: ">100 concurrent", "~10% cost".
# Bare integers are useless as forbidden phrases - "100" matches inside "1,006" and
# inside any year. Pairing the number with its noun keeps the block specific.
METRIC_BIGRAM_RE = re.compile(
    r"[$>~<]?\d[\d,]*(?:\.\d+)?\s*%?\+?\s+[A-Za-z][\w-]*"
)


def family_key(tag: Any) -> str:
    """'Tech Consulting' -> 'tech_consulting'. A trailing '?' (an unconfirmed tag) is dropped."""
    return re.sub(r"[\s\-]+", "_", str(tag).strip().rstrip("?").strip().lower())


def variants(bank: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The bank's `variants:` section, keyed by family_key.

    Each variant says how many bullets each role may carry (`budget`) and which
    records lead (`lead_order`). They live in the bank, not in code, because they
    are decisions about one person's resume.
    """
    return {family_key(k): v or {} for k, v in (bank.get("variants") or {}).items()}


@dataclass
class Item:
    """One evidence record, with the export decision attached."""
    eid: str
    role_id: str | None
    data: dict[str, Any]
    usable: bool = True
    reasons: list[str] = field(default_factory=list)   # why excluded, or caveats
    metric_ok: bool = False

    @property
    def confidence(self) -> str:
        return str(self.data.get("confidence", "low"))

    @property
    def status(self) -> str:
        return str(self.data.get("status", "unknown"))

    def block(self, reason: str) -> None:
        self.usable = False
        self.reasons.append(reason)


def _clean(text: Any) -> str:
    """YAML block scalars arrive with newlines. Resumes do not want them."""
    return " ".join(str(text or "").split())


def _is_placeholder(text: Any) -> bool:
    return any(m in str(text or "").upper() for m in UNSOURCED_MARKERS)


def load_bank(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def owner_name(bank: dict[str, Any]) -> str:
    for key in ("owner", "candidate", "name"):
        if key in bank and isinstance(bank[key], str):
            return bank[key].strip()
    return "UNKNOWN - bank has no owner/name key"


def assess(bank: dict[str, Any], variant: str | None) -> list[Item]:
    """Decide, per record, whether it may be exported and whether its metric may be."""
    roles = {r["role_id"]: r for r in bank.get("roles", [])}
    labels = {k: v.get("label", k) for k, v in variants(bank).items()}
    items: list[Item] = []

    for rec in bank.get("evidence", []):
        eid = rec.get("evidence_id", "<no id>")
        role_id = rec.get("role_id")
        item = Item(eid=eid, role_id=role_id, data=rec)

        # --- retired: merged into another record ----------------------------
        # A record folded into another must not be exported beside it, or one
        # event reads as two achievements.
        if rec.get("merged_into"):
            item.block(f"retired - merged into {rec.get('merged_into')}")

        # --- the record must belong to a real role ---------------------------
        if role_id not in roles:
            item.block(
                f"role_id {role_id!r} is not a defined role - attribution unresolved"
            )

        # --- a metric needs a real, stated source ----------------------------
        metric = rec.get("metric")
        source = rec.get("metric_source")
        if metric:
            if not source:
                item.reasons.append(f"metric {metric!r} dropped: metric_source is null")
            elif _is_placeholder(source):
                item.reasons.append(
                    f"metric {metric!r} dropped: metric_source is a placeholder"
                )
            else:
                item.metric_ok = True

        # --- R4: unfinished work may not use completed-tense verbs -----------
        if item.status in INCOMPLETE_STATUSES:
            used = sorted(
                v for v in BANNED_COMPLETED_VERBS
                if re.search(rf"\b{v}\b", _clean(rec.get("action")), re.I)
            )
            if used:
                item.block(
                    f"status={item.status} but action uses completed-tense verb(s): "
                    f"{', '.join(used)}"
                )
            else:
                item.reasons.append(f"status={item.status} - completed-tense verbs barred")

        # --- unresolved placeholders anywhere in the record ------------------
        for key in ("team_size", "leadership_scope", "outcome", "period"):
            if key in rec and _is_placeholder(rec[key]):
                item.block(f"{key} is unresolved ({_clean(rec[key])[:40]})")

        # --- disclosure ------------------------------------------------------
        disclosure = rec.get("disclosure", "public")
        if disclosure == "private":
            item.block("disclosure: private - interview prep only, never a document")
        elif disclosure == "restricted":
            item.reasons.append(
                "disclosure: restricted - only the permitted generic form may be used"
            )

        # --- variant eligibility --------------------------------------------
        if variant:
            families = [family_key(f) for f in rec.get("job_families", [])]
            if family_key(variant) not in families:
                item.block(
                    f"not tagged {labels.get(family_key(variant), variant)} - out of "
                    f"scope for this variant, not weak evidence"
                )

        items.append(item)
    return items


def apply_budget(items: list[Item], variant: str, bank: dict[str, Any]
                 ) -> tuple[list[Item], list[Item]]:
    """Over budget is a cut with a recorded reason, never silent truncation."""
    known = variants(bank)
    key = family_key(variant)
    # An unknown variant must not fall through to "no cap".
    if key not in known:
        raise ValueError(
            f"no bullet budget for variant {variant!r}; known: {', '.join(known)}. "
            "Add it under `variants:` in the bank before tailoring."
        )
    budget = known[key].get("budget") or {}
    lead = list(known[key].get("lead_order") or [])
    label = known[key].get("label", key)
    kept: list[Item] = []
    cut: list[Item] = []
    by_role: dict[str | None, list[Item]] = {}

    for it in (i for i in items if i.usable):
        by_role.setdefault(it.role_id, []).append(it)

    def rank(item: Item) -> tuple[int, bool, int]:
        # 1. the variant's designated lead records, in their stated order
        # 2. then metric-backed records
        # 3. then confidence
        lead_rank = lead.index(item.eid) if item.eid in lead else len(lead) + 1
        return (lead_rank, not item.metric_ok, CONFIDENCE_RANK.get(item.confidence, 9))

    for role_id, group in by_role.items():
        group.sort(key=rank)
        cap = budget.get(str(role_id), len(group))
        kept.extend(group[:cap])
        for position, it in enumerate(group[cap:], start=cap + 1):
            basis = "variant lead order" if it.eid in lead else "metric backing then confidence"
            it.reasons.append(
                f"budget: {role_id} capped at {cap} for {label}; "
                f"ranked {position} on {basis}"
            )
            cut.append(it)
    return kept, cut


def render_cv(bank: dict[str, Any], kept: list[Item], variant: str | None) -> str:
    """cv.md - the derived CV every tailored document is checked against."""
    roles = {r["role_id"]: r for r in bank.get("roles", [])}
    out: list[str] = []
    a = out.append

    a(f"# {owner_name(bank)}")
    a("")
    a("<!-- GENERATED by resume_gate.bank_export from the evidence bank.")
    a("     Do not hand-edit. Edit the bank and re-export.")
    a(f"     variant: {variant or 'master'} -->")
    a("")
    a("## Experience")
    a("")

    by_role: dict[str, list[Item]] = {}
    for it in kept:
        by_role.setdefault(str(it.role_id), []).append(it)

    for role_id, role in roles.items():
        group = by_role.get(role_id)
        if not group:
            continue
        end = role.get("end") or "Present"
        a(f"### {role['title']} — {role['employer']}")
        a(f"{role.get('location', '')} | {role['start']} – {end}")
        a("")
        for it in group:
            a(f"- {bullet_text(it)}  <!-- {it.eid} -->")
        a("")

    edu = bank.get("education") or []
    if edu:
        a("## Education")
        a("")
        for e in edu:
            cred = _clean(e.get("credential"))
            end = e.get("end") or "in progress"
            line = f"- **{e.get('institution')}** — {cred} ({e.get('start')} – {end})"
            status = str(e.get("status", ""))
            if status and status != "conferred":
                line += f"  <!-- status: {status}; not yet conferred -->"
            a(line)
        a("")

    sk = bank.get("skills") or {}
    if sk:
        a("## Skills")
        a("")
        for group_name, vals in sk.items():
            if isinstance(vals, dict):
                pretty = ", ".join(f"{k} ({v})" for k, v in vals.items())
            else:
                pretty = ", ".join(str(v) for v in vals)
            a(f"- **{group_name.replace('_', ' ').title()}**: {pretty}")
        a("")
    return "\n".join(out)


def bullet_text(item: Item) -> str:
    """Action, plus outcome, plus the metric only when its source is real."""
    parts = [_clean(item.data.get("action"))]
    outcome = _clean(item.data.get("outcome"))
    if outcome and not _is_placeholder(outcome):
        parts.append(outcome)
    if item.metric_ok:
        metric = _clean(item.data.get("metric"))
        # A record may state its result in both `outcome` and `metric`; print it once.
        first_token = metric.split(";")[0].strip().lower()
        if first_token not in outcome.lower():
            parts.append(metric)
    return " ".join(p.rstrip(".") + "." for p in parts if p)


def self_check(cv_text: str, facts: dict[str, Any]) -> list[tuple[str, str]]:
    """Does the generated CV violate the gate it just generated?

    It can, and on the first real run it did: a metric blocked in the `metric`
    field was still sitting in the same record's `outcome` prose, and withdrawn
    claims lived in `action` free text where no field-level rule reaches them.
    Writing a cv.md that fails its own gate is worse than writing nothing, so this
    blocks the export instead.
    """
    violations: list[tuple[str, str]] = []
    lowered = cv_text.lower()
    for phrase in facts["forbidden_phrases"]:
        idx = lowered.find(phrase.lower())
        if idx == -1:
            continue
        line_start = cv_text.rfind("\n", 0, idx) + 1
        line_end = cv_text.find("\n", idx)
        context = cv_text[line_start:line_end if line_end != -1 else None]
        eid = re.search(r"<!--\s*(EV-\d+)\s*-->", context)
        violations.append((phrase, eid.group(1) if eid else context[:60]))
    return violations


def _forbid_metric_text(value: str) -> list[str]:
    phrases = []
    for token in METRIC_RE.findall(value):
        token = token.strip()
        # Only distinctive tokens. A bare integer is too broad to block on.
        if len(token) > 1 and any(c in token for c in "%+$,"):
            phrases.append(token)
    for bigram in METRIC_BIGRAM_RE.findall(value):
        phrases.append(" ".join(bigram.split()))
    return phrases


def build_facts(bank: dict[str, Any], items: list[Item]) -> dict[str, Any]:
    """cv-facts.json - what a downstream fact gate may allow and must refuse."""
    allow_metrics: list[str] = []
    forbidden: list[str] = []

    # `metric_withheld` is a third state: a number that EXISTS and may even be real,
    # but has not been cleared for use. Without it, a record holding one confirmed
    # and one unconfirmed figure forces an all-or-nothing choice, and clearing the
    # confirmed one silently clears the other.
    for it in items:
        for held in it.data.get("metric_withheld") or []:
            value = _clean(held.get("value") if isinstance(held, dict) else held)
            if value:
                forbidden += _forbid_metric_text(value)

    for it in items:
        metric = _clean(it.data.get("metric"))
        if not metric:
            continue
        if it.metric_ok and it.usable:
            allow_metrics.append(metric)
        else:
            # Every number whose source did not survive becomes un-printable.
            forbidden += _forbid_metric_text(metric)

    # Claims the owner has ruled out globally. They live in the bank rather than
    # in code, where a reader of the YAML would never see them.
    forbidden += [str(p) for p in (bank.get("forbidden_claims") or []) if str(p).strip()]

    # Completed-tense verbs are barred for unfinished records; phrase matching needs
    # the verb paired with the project it may not be applied to.
    for it in items:
        if it.status in INCOMPLETE_STATUSES:
            project = _clean(it.data.get("project"))
            for verb in sorted(BANNED_COMPLETED_VERBS):
                forbidden.append(f"{verb} the {project}")

    allow_facts = []
    for r in bank.get("roles", []):
        allow_facts += [r["employer"], r["title"]]
    for e in bank.get("education", []):
        allow_facts.append(e.get("institution", ""))

    return {
        "_generated_by": "resume_gate.bank_export - do not hand-edit",
        "allow_metrics": sorted(set(allow_metrics)),
        "allow_facts": sorted({f for f in allow_facts if f}),
        "forbidden_phrases": sorted(set(forbidden)),
        "warn_phrases": WARN_PHRASES + list(bank.get("warn_phrases") or []),
    }


def render_report(bank: dict[str, Any], items: list[Item], kept: list[Item],
                  variant: str | None) -> str:
    """Every cut carries a reason, and the reason distinguishes 'out of scope for
    this variant' from 'weaker evidence'."""
    kept_ids = {i.eid for i in kept}
    out: list[str] = []
    a = out.append
    a(f"# Bank export report - variant: {variant or 'master'}")
    a("")
    a(f"Evidence records: {len(items)} · included: {len(kept)} · "
      f"excluded: {len(items) - len(kept)}")
    a("")
    a("## Included")
    a("")
    for it in kept:
        metric = f" [metric: {_clean(it.data.get('metric'))}]" if it.metric_ok else ""
        a(f"- **{it.eid}** ({it.role_id}) {_clean(it.data.get('project'))}{metric}")
        for r in it.reasons:
            a(f"    caveat: {r}")
    a("")
    a("## Not used")
    a("")
    for it in items:
        if it.eid in kept_ids:
            continue
        a(f"- **{it.eid}** {_clean(it.data.get('project'))}")
        for r in it.reasons:
            a(f"    reason: {r}")
    a("")
    questions = bank.get("open_questions", [])
    open_q = [q for q in questions if q.get("status") not in ("answered", "superseded")]
    closed = len(questions) - len(open_q)
    a(f"## Open questions still unresolved ({len(open_q)} open, {closed} closed)")
    a("")
    for q in sorted(open_q, key=lambda q: {"HIGH": 0, "MEDIUM": 1}.get(q.get("severity"), 2)):
        a(f"- **{q.get('id')}** ({q.get('severity')}) {_clean(q.get('issue'))}")
    return "\n".join(out)


def export(bank: dict[str, Any], variant: str | None
           ) -> tuple[str, dict[str, Any], str, list[tuple[str, str]]]:
    """(cv_text, facts, report, self-check violations). Writes nothing."""
    items = assess(bank, variant)
    if variant:
        kept, _cut = apply_budget(items, variant, bank)
    else:
        kept = [i for i in items if i.usable]
    cv_text = render_cv(bank, kept, variant)
    facts = build_facts(bank, items)
    report = render_report(bank, items, kept, variant)
    return cv_text, facts, report, self_check(cv_text, facts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--bank", type=Path, default=None,
                   help="evidence bank YAML (default: profiles/experience_bank.yaml, "
                        "else the fictional example)")
    p.add_argument("--out", type=Path, required=True,
                   help="directory to write cv.md and cv-facts.json into")
    p.add_argument("--variant", help="filter by job_families and apply the bullet budget")
    p.add_argument("--dry-run", action="store_true",
                   help="print the report, write nothing")
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    bank = load_bank(args.bank or paths.default_bank())
    try:
        cv_text, facts, report, violations = export(bank, args.variant)
    except ValueError as exc:
        print(f"BLOCKED - {exc}")
        return 1

    print(report)
    print()
    print(f"allow_metrics      : {len(facts['allow_metrics'])}")
    print(f"forbidden_phrases  : {len(facts['forbidden_phrases'])}")

    if violations:
        print()
        print("=" * 72)
        print(f"BLOCKED - the generated cv.md violates its own fact gate "
              f"({len(violations)} phrase(s)).")
        print("=" * 72)
        for phrase, where in violations:
            print(f"  {where:<10} contains forbidden phrase: {phrase!r}")
        print()
        print("These live in `action` / `outcome` free text, where no field-level rule")
        print("reaches them. Fix the bank and re-run. Nothing was written.")
        return 1

    if args.dry_run:
        print("\n(dry run - nothing written)")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    cv_path = args.out / "cv.md"
    facts_path = args.out / "cv-facts.json"
    report_path = args.out / "bank-export-report.md"
    cv_path.write_text(cv_text, encoding="utf-8")
    facts_path.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")

    print(f"\nwrote {cv_path}")
    print(f"wrote {facts_path}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
