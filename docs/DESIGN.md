# job-search-agent: design

This is the design of the full job-search agent. The owner's private version holds their
real evidence bank and application history. **This public repository contains the
provenance layer:** the evidence-bank format, the validator, the resume exporter, the PDF
check and the database schema. It uses fictional example data. The table in
[§ Build phases](#build-phases) shows which parts are here and which are not.

---

## Scope

**In scope:** evidence bank → job discovery → dedupe → eligibility filter → fit scoring →
resume tailoring with bullet-level provenance validation → prepared application package →
review queue → tracking. Assisted submission is also in scope, but only behind a
per-application human approval (C4).

**Out of scope:** unattended submission of any kind. Standing or bulk approvals. Bypassing
CAPTCHA, MFA, SSO or bot detection (C3). Auto-answering sensitive fields (C2).

**Guiding rule:** application accuracy beats application volume, always. Automation may
find, score, tailor and pre-fill at any scale. A human reviews each application before it
goes out, and the whole system exists to make that review cheap and trustworthy.

The project started from a concrete failure. A hand-tailored resume contained three
separate attribution errors, including an award filed under a role that had ended the year
before. So the validator was built before anything else.

---

## Non-negotiable constraints

### C1: provenance is enforced in code, not in prose

- Every generated bullet carries one or more `evidence_id`.
- Validation runs after every tailoring pass and **blocks**; it does not just warn.
- A bullet whose evidence_id does not exist, or whose record falls outside its role's
  `start`/`end`, is a hard failure.
- `status: pre-release | prototype` evidence must not produce completed-tense verbs
  (built, launched, shipped, deployed, delivered, released).
- A metric may appear only if its record has a real `metric_source`.

### C2: sensitive fields are never inferred

These go to the review queue unless an explicitly approved answer exists: work
authorization, visa status, sponsorship, CPT/OPT/F-1, immigration status, legal
attestations, criminal history, disability, race/ethnicity, gender, veteran status, any EEO
question, salary expectations, relocation, start date, security clearance, non-compete,
conflicts of interest, truthfulness certification, e-signature, references.

E-signatures and truthfulness certifications are human-only even when a stored value
exists. Any unrecognised form field is treated as sensitive by default.

### C3: no protection bypass

Never defeat CAPTCHA, MFA, SSO, email or SMS verification, rate limits, or bot detection.
Halt, mark `REQUIRES_HUMAN_ACTION`, record the blocker and continue to the next job.

### C4: human review gate before submission

- **Nothing is submitted without a human approving that specific application.** Not a
  config flag, not a standing approval, not "approve all". One application, one approval.
- The approval screen shows at least the employer, the role, the exact resume that will be
  sent, every bullet with its `evidence_id`, the gap list and every form answer.
- Approval is recorded with a timestamp. A submission attempt with no matching approval is
  a bug that must fail loudly.
- C2 and C3 still apply inside an approved application.

Any service that receives personal data (LLM provider, search API, plugin) is listed in a
data-egress report. That is a disclosure requirement, not a prohibition.

---

## Architecture

```text
config/        job_preferences.yaml · scoring_weights.yaml · application_answers.yaml
profiles/      experience_bank.yaml                 (gitignored: the real bank)
resumes/       master/ · variants/{swe,tpm,tech_consulting,fde,gtm_engineer}/ · tailored/{JOB_ID}/
data/          agent.db (SQLite, source of truth) · evidence_proposals/
applications/  {JOB_ID}/  prepared package: resume, answers, checklist
interviews/    {JOB_ID}/
src/job_agent/ db · models · paths · validator · bank_export · pdf_fill
```

### Database

`roles` · `evidence` · `open_questions` · `jobs` · `rejected_jobs` · `scores` ·
`tailored_resumes` · `bullet_provenance` · `applications` · `review_queue` ·
`blocker_queue` · `outcomes`. The schema is in [`src/job_agent/db.py`](../src/job_agent/db.py).

`bullet_provenance (resume_id, bullet_index, evidence_id)` is the important one. A tailored
resume with no provenance rows is a bug, not a state (`db.orphan_bullets()` must be 0).

---

## Discovery

Official, public ATS job-board endpoints only. They change, so each is verified at build time:

| ATS | Public job board endpoint pattern |
|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Lever | `api.lever.co/v0/postings/{company}?mode=json` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{name}` |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings` |

A curated list of 30–50 target companies beats crawling everything, on both quality and
legal exposure. Dedupe on normalised `(company, title, location)`, canonical URL and ATS job
id. Flag reposts and anything already applied to.

---

## Scoring

| Component | Weight |
|---|---|
| Must-have coverage (evidence-backed) | 30 |
| Relevant experience depth and recency | 25 |
| Role and responsibility alignment | 20 |
| Preferred skills | 10 |
| Seniority match | 5 |
| Location / work mode | 5 |
| Work authorization compatibility | 5 |

- A must-have counts as covered **only** if it maps to a real `evidence_id`. A keyword match
  alone scores zero. This is the whole point.
- Any missing must-have caps the total at 79.
- A hard eligibility failure (sponsorship required but not offered, clearance required, wrong
  country) is an immediate `SKIP` with a reason. No score is computed.
- Deterministic and reproducible. If an LLM takes part: temperature 0, cached by JD hash.

---

## Tailoring

1. Parse the JD into must-haves, preferred skills, responsibilities, seniority and keywords.
   Deterministic parsing comes first.
2. Select evidence using the variant's weighting and bullet budget.
3. Rewrite the phrasing only, never the facts. Emphasis and ordering may change; claims may not.
4. Validate. On failure, abort and report. Never emit a partial resume.
5. Write a report listing every bullet with its evidence_ids, and every gap deliberately
   left uncovered.

The LLM prompt includes, verbatim:

> Only use claims supported by the supplied candidate evidence records. Never fabricate
> experience, metrics, skills, responsibilities, employers, dates, or achievements. Cite the
> evidence_id for every bullet you produce. If the job description requires something not
> present in the evidence, output it under `gaps` instead of writing a bullet. Evidence marked
> `status: pre-release` or `prototype` must not be described with completed-tense verbs.

The prompt is a request. The validator is the guarantee.

---

## Variants

A variant is one job family: SWE, TPM, Tech Consulting, FDE, GTM Engineer. Variants differ
in emphasis and ordering only, never in facts. A record is eligible for a variant only if
its own `job_families` tag says so. When a title fits two variants, the JD's
responsibilities decide: post-sale deployment and integration → FDE; pre-sale demos and
pipeline → GTM Engineer; advisory deliverables without building → Tech Consulting.

A variant the evidence cannot support is refused, not generated. Reframing unrelated work to
fit a job family is fabrication with extra steps.

### V1: bullet budget

A one-page resume has a fixed budget. Eligibility alone does not earn a line: without a cap,
one long role produces a wall of bullets and buries the most relevant record. Each variant
sets a maximum per role, in the bank:

```yaml
variants:
  swe:
    budget: {R-LEAD: 3, R-ENG: 2, R-INDIE: 1}
    lead_order: [EV-21, EV-02, EV-09]
```

- The cap is enforced in code. Over budget is a cut with a recorded reason, never silent
  truncation.
- Selection order: the variant's lead records first, then metric-backed records, then
  confidence.
- An unknown variant is an error, not an unlimited budget.

### V2: every cut is recorded with its reason

The export report lists both halves of the decision, and the wording of a cut matters:

```text
$ python -m job_agent.bank_export --variant fde --out build --dry-run
...
## Not used
- **EV-05** Merchant network growth
    reason: budget: R-LEAD capped at 4 for FDE; ranked 5 on metric backing then confidence
- **EV-09** Returns-processing service
    reason: not tagged FDE - out of scope for this variant, not weak evidence
```

A record cut for budget or variant fit is not a weak record. When the same bank is
recomposed for a different job family next week, the report makes it obvious why the shape
changed.

---

## Interview support

The interview is where you find out what your evidence is actually worth. An interviewer
asking "measured against what baseline?" is an open question arriving in person.

- **brief:** company, role, the JD verbatim, the resume that was actually sent, and the
  gaps that were deliberately not covered.
- **prep:** likely questions from the JD's must-haves, each mapped to the evidence_id you
  would answer with. A must-have with no evidence is listed under "you cannot answer this
  from the bank". That is the honest output, not a generated answer.
- **debrief:** what was asked and what you could not answer. The debrief writes
  **proposals**, never the bank itself. A proposal is not evidence until the owner applies
  it by hand.

---

## Outcome loop

Track submitted, responded, outcome, days to response, variant and fit score. After 20+
applications, report conversion by variant and score band. Weights are not tuned before
that data exists.

---

## Build phases

| Phase | Deliverable | In this repository |
|---|---|---|
| 0 | Environment check | — |
| 1 | Security review of candidate repos | [`docs/REPO_REVIEW.md`](REPO_REVIEW.md) |
| 2 | Skeleton and SQLite schema | ✅ `db.py`, `tests/test_db.py` |
| 3 | Evidence bank and validator; a corrupted record must fail | ✅ `validator.py`, 29 fixtures |
| 4 | Discovery (Greenhouse, Lever) | Delegated to career-ops; not here |
| 5 | Scoring | Designed above; not here |
| 6 | Tailoring, with every bullet traced and one gap refused | ✅ export side: `bank_export.py` (V1 budget, V2 report, self-check). The LLM rewriting step is not here |
| 7 | Prepared package and review queue | Schema only (`review_queue`, `blocker_queue`) |
| 8 | Reporting and outcome loop | Schema only (`outcomes`) |
| 9 | Interview support | Designed above; not here |
| 10 | Approval gate, proven by a test that tries to skip it | Designed above; not here |
| 11 | Assisted submission | Not started. It waits for Phase 10's skip-the-gate test to pass |

Phase 10 is built **before** Phase 11. The gate is the feature; submission is the convenience.

---

## Build or adopt

Phase 1 reviewed seven open-source candidates ([`REPO_REVIEW.md`](REPO_REVIEW.md)) and
recommended writing everything in-house. The owner overruled that for the plumbing and
adopted **career-ops** (MIT, actively maintained) for discovery, dedupe, tracking and the
dashboard. The layer none of the candidates had stays in-house:

| Layer | Source |
|---|---|
| Discovery, dedupe, tracking, dashboard, submission plumbing | career-ops |
| Evidence bank, bullet provenance, date-range and metric-source enforcement, V1 budget, V2 cut rationale | **this project** |
| Approval gate (C4) | **this project** |

career-ops has fact checking, but it asks a model whether a CV looks truthful. This project
proves where each bullet came from. Any path that produces a resume must go through the
validator, or be disabled.

---

## LLM configuration

Provider-agnostic. Deterministic code handles dedupe, filtering and scoring arithmetic. An
LLM is used only for JD requirement extraction and bullet rephrasing, and its output is
validated like anything else.
