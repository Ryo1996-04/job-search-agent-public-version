# resume-fact-gate

[![tests](https://github.com/Ryo1996-04/resume-fact-gate/actions/workflows/tests.yml/badge.svg)](https://github.com/Ryo1996-04/resume-fact-gate/actions/workflows/tests.yml)

**A validator that blocks resume claims your own evidence can't back up.**

Tailoring a resume for every application, by hand or with an LLM, drifts. A number
gets rounded up, an unfinished project becomes "shipped", an award slides under the
wrong job. Each edit looks harmless and nobody re-checks the whole page.

`resume-fact-gate` treats your experience as data. Every claim lives once, in a YAML
**evidence bank** you maintain. Every resume is checked against the bank before
anyone reads it, and a claim the bank can't support is blocked, not just flagged.

```text
$ python -m resume_gate.validator tests/fixtures/03-invented-metric.md

  ERROR METRIC      '35%' is not a metric any sourced record supports
              -> Add it to a record's `metric` with a real `metric_source`, or remove it. No source, no number.
  ERROR METRIC      '60%' is not a metric any sourced record supports
              -> Add it to a record's `metric` with a real `metric_source`, or remove it. No source, no number.

2 error(s), 0 warning(s). BLOCKED.
```

The 35% was never in the bank. Nobody had to think to blocklist it: a number with no
sourced record behind it fails on its own.

## How it works

```text
                   examples/experience_bank.example.yaml   (or your own, gitignored)
                     roles · evidence records · variants · forbidden claims
                                        │
              ┌─────────────────────────┴─────────────────────────┐
              ▼                                                   ▼
   resume_gate.bank_export                              resume_gate.validator
   bank → cv.md + cv-facts.json + report                any resume.md → OK / BLOCKED
   (per-variant bullet budgets, every cut explained)    (the rules below)
              │                                                   ▲
              └──────── the exported cv.md must pass ─────────────┘
```

Each evidence record carries its own constraints: which role it belongs to, when
it happened, whether it shipped, where its number comes from, and which words must
travel with that number. The validator enforces them.

```yaml
- evidence_id: EV-21
  role_id: R-INDIE
  period: 2026-09
  action: Benchmarked orjson vs. the standard-library json module on large order exports.
  metric: "3.1x faster parsing; 2.2x end-to-end (median of 50 runs, 2026)"
  metric_requires_qualifier: ["2026", "50", median]   # bare "3.1x faster" is blocked
  metric_source: Benchmark script output, committed with the script
  status: shipped
```

## Rules

| Code | Blocks | Example it catches |
|---|---|---|
| `METRIC` | a number no sourced record supports | "reduced latency by 35%", when no record says 35% |
| `FORBIDDEN` | a phrase the bank has withdrawn | a claim that was corrected once, coming back in a rewrite |
| `V13` | an organisation the bank never mentions | "Senior Engineer, Acme Robotics Corporation" |
| `R4` | completed-tense verbs about unfinished work | "built and launched" a project whose status is `pre-release` |
| `V19` | a figure printed without its qualifiers | "3.1x faster", when it is only true as a median of 50 runs in 2026 |
| `DISCLOSURE` | a record marked `private` (e.g. under NDA) | naming a confidential partner agreement |
| `V16` | sole-ownership claims | "single-handedly migrated..." |
| `V4` | an experience bullet with no `<!-- EV-xx -->`, or citing an id that doesn't exist | `<!-- EV-99 -->` |
| `R3` | a record under the wrong role, or dated outside its role | a 2021 award under a job that ended in 2020 |
| `V17` *(warn)* | filler that says nothing checkable | "passionate, results-driven self-starter" |
| `TAG` *(warn)* | a provenance tag that would print on the page | `[EV-09 · SWE]` in the visible text |

`V4` and `R3` run with `--expect-provenance`. Every rule has at least one test
fixture in [`tests/fixtures/`](tests/fixtures/): 29 short fictional resumes, each
breaking one rule, plus clean controls that must pass.

## Quick start

```bash
git clone https://github.com/Ryo1996-04/resume-fact-gate.git
cd resume-fact-gate
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

Check a resume, then export a tailored CV for one job family:

```bash
python -m resume_gate.validator tests/fixtures/17-valid-multi-id.md --expect-provenance
python -m resume_gate.bank_export --variant fde --out build/
```

`bank_export` writes `build/cv.md`, a `cv-facts.json` of allowed metrics and
forbidden phrases, and a report that gives a reason for every record it left out,
separating "out of scope for this variant" from "weaker evidence". It refuses to
write a CV that would fail its own fact check.

`pdf_fill` checks the rendered PDF: at most one page, and a warning when the page
is under-filled.

```bash
python -m resume_gate.pdf_fill resume.pdf
```

## Using your own bank

Copy `examples/experience_bank.example.yaml` to `profiles/experience_bank.yaml`
and replace the records with your own. `profiles/` is gitignored, and the tools
pick up that file automatically when it exists.

## Privacy

This project was extracted from a private one that holds a real person's resume
data. All the data here is invented. That is enforced by a check, so it does not
depend on anyone being careful:

- [`tools/privacy_scan.py`](tools/privacy_scan.py) scans every file for email
  addresses, phone numbers, home-directory paths, profile URLs, links to unlisted
  hosts and files that must never be tracked. It also checks against a denylist of
  personal terms that is stored **only as salted hashes**. The plaintext list never
  enters the repository.
- It runs in CI on every push, and as a test (`tests/test_privacy.py`). The tests
  also run the scanner on crafted inputs, to prove it catches what it claims to.
- An optional pre-commit hook blocks a leak before it is committed:
  `git config core.hooksPath .githooks`

## Limitations

- `METRIC` checks numbers shaped like results (`35%`, `3.1x`, `$1,500`, `12,000`,
  `300+`). A bare integer ("4 threads") is not checked, because it would make every
  document fail.
- Organisations are detected by shape ("... Inc.", "... University"). An employer
  written without a suffix is not recognised.
- Rules and messages assume English-language resumes.

Developed with [Claude Code](https://claude.com/claude-code) as a pair programmer.

## License

MIT
