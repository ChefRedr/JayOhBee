# CLAUDE.md

Personal automated new-grad SWE job hunter + auto-apply bot ("jobbot").
Single-user tool, not a platform. Python 3.12, package `jobbot/`, config in
`config/`, tests in `tests/`.

## Commands

```bash
.venv/bin/python -m pytest -q          # run tests (fast, no network)
.venv/bin/python -m jobbot status      # registry/job health
.venv/bin/python -m jobbot discover    # Stage A source discovery (network-heavy)
.venv/bin/python -m jobbot scan --dry-run --company <slug>   # safe pipeline test
```

## Architecture in one breath

`config/companies.yaml` (registry, human-editable, committed) → `sources/`
(one adapter per ATS, bulk public APIs, normalized into `models/job.py:Job`) →
`filters/eligibility.py` (deterministic rules from `config/filters.yaml`) →
`storage/database.py` (SQLite in `state/`, authoritative; dedup by
`Job.identity` = provider:company:external_id) → `applications/` (Playwright
adapters fill hosted forms from `config/applicant.yaml`) →
`integrations/` (Google Sheets mirror + SMTP email). `runner.py` orchestrates;
`discovery/` populates the registry.

## Hard rules — do not weaken these

- **Never guess application answers.** `applications/form_mapping.py:resolve`
  returns None for anything not explicitly configured; that must route the
  application to `needs_review`. Essay/clearance/legal questions are in
  `_ALWAYS_REVIEW` and must never be auto-answered even if configured keys match.
- **No CAPTCHA bypass, fingerprint spoofing, or anti-bot evasion.** When
  blocked, mark `needs_review` and stop.
- **Submitted ≠ clicked.** Only return `ApplicationStatus.SUBMITTED` after
  observing confirmation evidence (text/redirect). Seen ≠ applied: only a
  `submitted` row in `applications` marks a job done.
- **Discovery never fabricates.** A source is `verified` only after jobs were
  actually fetched from it; uncertain slug-probe hits stay `needs_review`.
- **Failure isolation:** one company/application failing must never abort the
  run (`runner.py` catches per-item).
- **Secrets:** `config/applicant.yaml`, `.env`, resumes, service-account JSON
  are gitignored — never commit or log them. Sheets is a mirror; SQLite is truth.

## Conventions

- `AUTO_APPLY` env gates real submissions; everything defaults to dry-run.
- Provider adapters prefer one bulk request over per-job requests (rate limits).
- `SourceError(retryable=...)` distinguishes retryable (timeouts, 5xx, 429)
  from config errors (404 → registry `needs_review`).
- New ATS support = a `sources/<ats>.py` (fetch) and optionally
  `applications/<ats>.py` (apply); register both in their `__init__.py` maps.
  Unsupported providers automatically fall back to `GenericApplicationAdapter`
  (manual review).
- Tests use sanitized fixtures in `tests/fixtures/` + the `fake_get` fixture;
  never depend on live sites in tests.
- GitHub Actions state: SQLite lives on the force-pushed single-commit `state`
  branch (see `.github/workflows/jobbot.yml`); runners are ephemeral.
