# CLAUDE.md

Rules for any coding agent (Claude Code or otherwise) working on this repository.
[`docs/DESIGN.md`](docs/DESIGN.md) is the full design; this file is the short version
of the rules that must never be broken.

## What this project is

A job-search agent that turns a structured evidence bank into accurate, job-specific
resumes, and tracks applications. It finds, scores, tailors and pre-fills. Discovery and
tracking come from [career-ops](https://github.com/career-ops-hq/career-ops). The evidence
bank, provenance enforcement and approval gate are this project's own, and this repository
is their public version.

**It submits only what a human approved, one application at a time.**

## What this project is not

Not an unattended application bot. There is no bulk approval, no "approve all", no standing
authorisation, no scheduled submission. If a change would let an application go out without a
human seeing that specific package first, that change is out of scope. Stop and ask.

## Hard rules

1. **Never write a resume bullet without provenance.** Every bullet maps to one or more
   `evidence_id` in the bank. `python -m job_agent.validator <doc> --expect-provenance`
   blocks a bullet whose `<!-- EV-xx -->` comment is missing or cites an id that is not in
   the bank. Do not downgrade it to a warning. Do not add a bypass flag.

2. **Never let evidence escape its role's date range.** A record whose period falls outside
   its role's `start`/`end` is an error (rule R3), and so is a bullet under the wrong role
   heading. This check exists because a hand-edited resume once placed an award under a role
   that had already ended.

3. **Never use completed-tense verbs for unfinished work.** Records with
   `status: pre-release` or `prototype` cannot say built, launched, shipped, deployed,
   delivered or released (rule R4).

4. **Never emit a metric without `metric_source`.** If the source is null or a placeholder
   ("UNKNOWN", "VERIFY"), the number does not go in the resume (rule METRIC).

5. **Never fabricate.** If a job description asks for something the bank does not support,
   it goes in `gaps`. Do not close a gap with wording.

6. **Never auto-answer sensitive fields.** Work authorization, visa, sponsorship, EEO and
   demographic questions, criminal history, disability, salary, relocation, clearance, legal
   attestations, e-signatures, references. Unrecognised fields count as sensitive. They go to
   the review queue unless an approved answer exists.

7. **Never bypass CAPTCHA, MFA, SSO or bot detection.** Mark `REQUIRES_HUMAN_ACTION` and move on.

8. **Never submit without a recorded per-application approval.** No approval row for that
   exact job, no submission: raise, do not warn. No bulk approve, `--yes`, `--all`, or a
   config flag that pre-approves. Approving job A never approves job B.

9. **Never exceed the bullet budget.** Caps are per role, per variant, set in the bank's
   `variants:` section. An unknown variant is an error, not "no cap". Do not silently truncate.

10. **Never write an export report that lists only what was included.** Every cut record
    needs a reason, and the reason distinguishes "out of scope for this variant" from
    "weaker evidence".

11. **Always name what leaves the machine.** Any service that receives personal data (LLM
    provider, search API, plugin backend) must be disclosed. Sending is allowed; sending
    silently is not.

12. **Never commit personal data.** This repository ships fictional examples only. Real
    banks, resumes and applications live in gitignored folders. `python tools/privacy_scan.py`
    must pass before every commit (CI and the pre-commit hook enforce it).

## Working style

- Deterministic first. Do not reach for an LLM where parsing works.
- Small, readable modules. Prefer 800 lines a person can audit to 5,000 they cannot.
- Tests for the validator are not optional. Every rule gets a fixture that breaks it and a
  control that must pass.
- A check that examines nothing must say so. A silent pass is how a check that does nothing
  looks like one that works.

## Stop and ask

- Before weakening the approval gate in any way, including anything that makes approving
  faster by showing the user less.
- Before installing a third-party repo that touches browser profiles, cookies or credentials.
- Before changing a scoring weight or a bullet budget. The owner sets those.
- Before writing anything into a real evidence bank. The bank is the source of truth and only
  its owner amends it.
