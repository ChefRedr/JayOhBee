# JayOhBee

A personal automated new-grad SWE job hunter and auto-apply bot.

It watches ~500 target companies, detects newly posted entry-level software
engineering roles, and — when every required application question can be
answered safely from a predefined applicant profile — submits the application
automatically. Anything it can't answer confidently goes to a manual-review
queue instead of being guessed. Everything is logged to Google Sheets, and
notifications go out by email.

> A private personal daemon that repeatedly checks my target companies, notices
> new entry-level SWE jobs before I would manually, and submits applications
> for me whenever it has all information necessary to do so safely.

## How it works

```text
Company Registry (config/companies.yaml, built from top_500_swe_companies.csv)
       ↓
Job Source Discovery  — one-time: find each company's ATS + identifier
       ↓
ATS Adapters          — Greenhouse / Lever / Ashby / Workday / SmartRecruiters
       ↓
Deterministic Filter  — entry-level SWE titles, no seniors, no internships
       ↓
Deduplication         — SQLite; a job is only ever processed once
       ↓
Auto Apply            — Playwright fills the hosted form from your profile
       ↓
Google Sheets Log  +  Email Notifications
```

Two stages:

- **Stage A (once):** `jobbot discover` figures out where every company
  publishes jobs — it inspects the careers page, follows links, detects the
  ATS, extracts the board/tenant identifier, and proves the source works by
  actually fetching jobs. Uncertain results are marked `needs_review`, never
  silently verified.
- **Stage B (every 3 hours via GitHub Actions):** `jobbot run` fetches jobs
  from all verified sources, filters, dedupes, records, and applies.

## Safety model

The bot never guesses. An application is submitted only when **every required
field** maps to an explicitly configured answer. It routes to manual review on:
CAPTCHAs, login walls, essay questions, unknown sponsorship / work-authorization
/ clearance / GPA / salary questions, unconfigured EEO fields, missing files,
or any form structure the adapter doesn't understand. It does not bypass
CAPTCHAs or anti-bot measures. A job is only marked applied after the adapter
observes real confirmation evidence — not just because Submit was clicked.

The master switch is the `AUTO_APPLY` environment variable. Until it is
`true`, everything runs in dry-run mode: jobs are discovered, filtered,
recorded, and application feasibility is simulated, but nothing is submitted.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# personal config (both gitignored):
cp config/applicant.example.yaml config/applicant.yaml   # fill it in
cp .env.example .env                                     # Sheets / SMTP creds
```

Google Sheets: create a service account, share the spreadsheet with its email,
then set `GOOGLE_SERVICE_ACCOUNT_FILE` (or `..._JSON`) and
`SHEETS_SPREADSHEET_ID`. Sheets is optional — SQLite in `state/jobbot.db` is
always the authoritative state.

## CLI

```bash
python -m jobbot discover              # Stage A: find + verify ATS sources
python -m jobbot validate-companies    # re-check that verified sources still work
python -m jobbot scan [--dry-run]      # fetch + filter jobs, never applies
python -m jobbot run                   # full recurring run (respects AUTO_APPLY)
python -m jobbot apply [--limit N]     # attempt pending eligible applications
python -m jobbot retry                 # also retry previously failed ones
python -m jobbot status                # registry / job / application health
python -m jobbot import-companies FILE [--replace]   # .txt or .csv of names
```

## Configuration

| File | Purpose | Committed? |
|---|---|---|
| `top_500_swe_companies.csv` | ranked target-company list | yes |
| `config/companies.yaml` | registry: per-company ATS + identifier + status | yes |
| `config/filters.yaml` | deterministic eligibility rules | yes |
| `config/applicant.yaml` | your personal profile + predefined answers | **never** |
| `.env` | credentials | **never** |

Registry entries look like:

```yaml
- name: Figma
  slug: figma
  provider: greenhouse
  provider_identifier: figma
  enabled: true
  discovery_status: verified   # verified | needs_review | failed | pending
  last_verified: "2026-08-27"
```

Workday companies additionally need `workday_host` and `workday_site` (the
discovery step extracts these automatically from myworkdayjobs.com URLs).

## Job statuses

`discovered → filtered_out | eligible → application_started → applied |
needs_review | failed | closed`

"Seen" and "applied" are tracked separately: a failed application leaves the
job eligible for retry (max 3 attempts); only a confirmed submission marks it
done.

## Application adapters

| Provider | Fetching | Auto-apply |
|---|---|---|
| Greenhouse | public board API | ✅ Playwright (hosted form) |
| Lever | public postings API | ✅ Playwright (hosted form) |
| Ashby | public posting API | manual review queue |
| SmartRecruiters | public postings API | manual review queue |
| Workday | CXS JSON endpoint | manual review queue |
| iCIMS / Oracle / SuccessFactors / custom | not yet | manual review queue |

Public ATS APIs are used for discovery; applicant-side submission uses the
hosted forms via Playwright (employer API credentials are not assumed).

## GitHub Actions

`.github/workflows/jobbot.yml` runs every 3 hours (at :17) plus on manual
dispatch. Runners are ephemeral, so the SQLite database is persisted on a
dedicated `state` branch: restored at the start of each run, force-pushed as a
single fresh commit at the end.

Secrets to configure: `APPLICANT_YAML`, `RESUME_BASE64` (resume path in the
profile must be `/home/runner/resume.pdf`), optionally
`GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEETS_SPREADSHEET_ID`, and the `SMTP_*` /
`NOTIFY_EMAIL_*` set. Enable submissions by setting the repository **variable**
`AUTO_APPLY=true` once you've watched a few dry runs.

## Tests

```bash
pytest -q
```

Covers ATS detection, job normalization from sanitized fixtures, positive /
negative / experience filtering, deduplication, application state transitions,
and unknown-form-field behavior. No live websites required.

## Current status / roadmap

- [x] 500-company registry from `top_500_swe_companies.csv`
- [x] Automated ATS discovery with verification (`jobbot discover`)
- [x] Fetch adapters: Greenhouse, Lever, Ashby, Workday, SmartRecruiters
- [x] Deterministic entry-level filter + SQLite dedup
- [x] Google Sheets log + email notifications
- [x] Playwright auto-apply: Greenhouse, Lever (others queue for manual review)
- [x] Scheduled GitHub Actions runs with persistent state
- [ ] Ashby application adapter (next largest provider by coverage)
- [ ] Workday application adapter (accounts/login make this the hardest)
- [ ] Browser-assisted discovery for JS-only careers pages
- [ ] External signal sources (zero2sudo etc.) as additional discovery inputs
