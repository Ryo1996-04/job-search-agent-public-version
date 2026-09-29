# Phase 1 — Repository Security Review

> Historical record, kept as written in Phase 1. Its verdict on career-ops was later
> overruled by the owner, who adopted it for discovery and tracking while keeping the
> provenance layer in-house. See [DESIGN.md § Build or adopt](DESIGN.md#build-or-adopt).
> `SPEC.md` below is the private build spec; its public form is [DESIGN.md](DESIGN.md).

Date: 2026-09-20
Method: read-only inspection via the GitHub REST API (repo metadata, full file trees,
dependency manifests, and selected raw source files). **Nothing was cloned, installed, or executed.**
Scope: the seven candidates named in `SPEC.md` § Repository investigation.

## Verdict

**Adopt none. Write it ourselves.** — which is the outcome SPEC.md predicted.

No repository was found to be malicious. The rejections are on fit and auditability, with
one exception (`Job_search_agent`) that is rejected on security grounds.

Two repos contain *prompt material* worth reading for ideas. Reading a markdown prompt is not
adopting a dependency; see § Worth reading.

---

## Summary table

| Repo | Stars | License | Last push | Files | Deps | Verdict |
|---|---|---|---|---|---|---|
| `varunr89/resume-tailoring-skill` | 749 | MIT | 2026-03-01 | 16 (13 md) | none | Reject — no enforcement |
| `jordmorr/openclaw-jobsearch` | 1 | MIT | 2026-03-21 | 10 (5 md) | none | Reject — negligible content |
| `career-ops-hq/career-ops` | 72,250 | MIT | 2026-09-19 | 1,445 | 4 npm | Reject — unauditable at this size |
| `DanielPan12/JobHuntBot` | 827 | MIT | 2026-09-17 | 31 | none | Reject — CSV tracking, no provenance |
| `surapuramakhil-org/Job_search_agent` | 171 | **AGPL-3.0** | 2026-08-07 (**archived**) | 164 | ~56 | **Reject — security + ToS** |
| `Paramchoudhary/ResumeSkills` | 2,381 | MIT | 2026-06-19 | 82 (31 md) | none | Reject as code; read as prompts |
| `resume-craft` | — | — | — | — | — | No credible match found |

---

## Per-repo findings

### 1. `varunr89/resume-tailoring-skill` — REJECT (fit)

- MIT, 749★/124 forks, created 2025-11, last push 2026-03-01 (~6 months stale), 8 open issues
- 16 files: 13 markdown, 1 json, no source code, **no dependency manifest**
- Risk scan: clean. No network calls, no credentials, no browser automation, no LinkedIn

**Why reject:** it is a prompt-only Claude Code skill. Tailoring is instructed in prose, which
is exactly the failure mode SPEC.md C1 exists to eliminate — "provenance is enforced in code,
not in prose." It has no `evidence_id`, no validator, no date-range check. Adopting it would
mean adopting the problem this project was created to fix.

### 2. `jordmorr/openclaw-jobsearch` — REJECT (negligible)

- MIT, 1★, 10 files (5 md + 3 yaml), one week of activity in March 2026, no code
- Risk scan: clean

**Why reject:** there is essentially nothing in it. Single-author, single-week, one star.
Nothing to adopt and no maintenance signal.

### 3. `career-ops-hq/career-ops` — REJECT (unauditable)

- MIT, 72,250★/13,602 forks, **actively maintained** (pushed the day of this review), 545 open issues
- 1,445 files, 71 MB. 740 `.mjs`, 307 `.md`, 74 `.ts`, 73 `.tsx` — Node/Next.js, not Python
- Dependencies (root `package.json`): the Gemini SDK, `dotenv`, `js-yaml`, `playwright`

Risk items investigated and **cleared**:

- `linkedin-join.mjs` (942 lines) — despite the name, it is a *warm-intro finder*. It parses
  the CSV you export yourself from LinkedIn ("Connections.csv") and joins it against your
  target company list, then builds `linkedin.com/search/...` URLs for **you** to open.
  No login, no session cookie, no `li_at`, no Easy Apply, no scraping. This is
  "reading only, at human pace".
- `discard-analytics.mjs` — misleading name; it analyses your own local discard log for
  filter tuning. **Not telemetry.** Nothing leaves the machine.
- `playwright` — used for CV visual regression tests (`playwright.cv.config.mjs` →
  `testDir: './tests/cv-visual'`), not for form-filling. No `userDataDir`, no Chrome profile
  path, no cookie access anywhere in the tree.
- `.env.example` — standard provider keys (Gemini / OpenRouter / OpenAI). No harvesting.

**Why reject anyway:** CLAUDE.md says "prefer 800 lines you can read to 5,000 you cannot."
This is 1,445 files in the wrong language for our spec, with 545 open issues. You cannot audit
it, and an unauditable tool that writes your resume defeats the purpose. The architecture also
conflicts with SPEC.md (SQLite + Python + `bullet_provenance`).

*Reconsider only if* you decide you want an off-the-shelf system and are willing to give up
provenance enforcement. That is a different project, not this one.

### 4. `DanielPan12/JobHuntBot` — REJECT (fit)

- MIT, 827★/66 forks, created 2026-08, last push 2026-09-17 (active), 0 open issues
- 31 files: 14 CSV, 10 md, 1 html, 1 js. No dependency manifest — markdown-driven agent
  workflow plus a static local dashboard
- Risk scan: clean. No credentials, no browser automation, no LinkedIn, no network egress

**Why reject:** tracking is CSV files, our spec calls for SQLite with a `bullet_provenance`
table. No evidence model, no provenance, no validator. The local-dashboard idea is good and
worth stealing conceptually for Phase 8 reporting — the code is not worth adopting.

### 5. `surapuramakhil-org/Job_search_agent` — **REJECT (security + ToS)**

This is the only repo rejected on substance rather than fit. Four independent reasons:

1. **A key-shaped secret is committed to the repository.**
   `docs/data_folder_example/secrets.yaml` contains an `llm_api_key` value
   in OpenAI key format, in the example file, in git history. Whether or not it is live or
   revoked, a project that ships that pattern is teaching its users to commit secrets.
2. **It is an auto-apply bot with stored credentials.** `src/authenticator.py`,
   `src/job_applier.py`, `src/bot_facade.py`, `src/job_portals/lever/authenticator.py`,
   `src/utils/chrome_utils.py`, `src/utils/browser_utils.py`. It logs into job portals and
   submits on your behalf — directly prohibited by SPEC.md C3/C4 and CLAUDE.md rules 6–9.
3. **Archived.** `archived: true`, last push 2026-08-07. No maintainer, no security patches.
4. **AGPL-3.0.** The only copyleft license in the set. Irrelevant if you never distribute,
   but it is a real constraint you would be taking on for no benefit.

Do not clone this repository, including "just to look." Reading it through the API, as done
here, is sufficient.

### 6. `Paramchoudhary/ResumeSkills` — REJECT as code

- MIT, 2,381★/202 forks, last push 2026-06-19, 5 open issues
- 82 files, 31 markdown. Pure prompt/skill definitions, mirrored across `.claude/`, `.codex/`,
  `.cursor/`, `.agents/` directories. **No executable code, no dependencies**
- `linkedin-profile-optimizer` matched the LinkedIn path filter — it is a prompt for rewriting
  your own profile text, not automation. Cleared

**Why reject:** same reason as #1 — prompts, not enforcement.

### 7. `resume-craft` — NO CREDIBLE MATCH

Searched GitHub. The closest results are `Codevickk/resumeCraft` (last commit 2021-01, dead)
and `DevByGB/resume-craft` (a Next.js course exercise in Portuguese). Neither is a job-search
agent. Either the name in the spec is wrong, or the project was renamed or removed. Nothing to
review.

---

## Worth reading (not adopting)

Two sources of *prompt* material, to read and rewrite in our own words — no code, no
dependency, no supply chain:

- `Paramchoudhary/ResumeSkills` → `interview-prep-generator`, `job-description-analyzer`.
  Relevant to the interview module and to Phase 5 JD parsing.
- `DanielPan12/JobHuntBot` → the local progress dashboard layout, as a reference for Phase 8.

If you want either, say so and I will read them and summarise. They are markdown; nothing gets
installed.

---

## What this means for the build

Nothing changes. SPEC.md already assumed this outcome. The components that justify this
project — `bullet_provenance`, `validate_bullets()`, the date-range check, `metric_source`
enforcement — **do not exist in any of the seven repos**. Every one of them tailors resumes by
asking a model nicely.

Proceed to Phase 2.
