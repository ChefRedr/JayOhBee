"""jobbot command-line interface."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from jobbot.config import auto_apply_enabled, load_companies, save_companies
from jobbot.models.company import Company, DiscoveryStatus


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def cmd_discover(args) -> int:
    from jobbot.discovery.discover import run_discovery

    summary = run_discovery(limit=args.limit, rediscover=args.rediscover)
    print("\nDiscovery summary:")
    for key, value in sorted(summary.items(), key=lambda kv: -kv[1] if kv[0] != "total" else 0):
        print(f"  {key}: {value}")
    return 0


def cmd_validate(args) -> int:
    """Re-verify that every verified company's source still returns jobs."""
    from jobbot.sources import get_source
    from jobbot.sources.base import SourceError

    companies = load_companies()
    broken = 0
    for company in companies:
        if not company.is_runnable:
            continue
        source = get_source(company.provider)
        if source is None:
            print(f"UNSUPPORTED {company.name}: provider {company.provider}")
            continue
        try:
            jobs = source.fetch_jobs(company)
            print(f"OK      {company.name}: {len(jobs)} jobs ({company.provider})")
        except SourceError as exc:
            broken += 1
            print(f"BROKEN  {company.name}: {exc}")
            if not exc.retryable:
                company.discovery_status = DiscoveryStatus.NEEDS_REVIEW
                company.notes = f"validation failed: {exc}"
    save_companies(companies)
    print(f"\n{broken} broken source(s)")
    return 0


def cmd_scan(args) -> int:
    from jobbot.runner import run_pipeline

    metrics = run_pipeline(
        apply_stage=False,
        record=not args.dry_run,
        company_slugs=args.company or None,
    )
    print(json.dumps(metrics, indent=2))
    return 0


def cmd_run(args) -> int:
    from jobbot.runner import run_pipeline

    print(f"AUTO_APPLY={'true' if auto_apply_enabled() else 'false'} "
          f"({'submissions ENABLED' if auto_apply_enabled() else 'dry-run, nothing will be submitted'})")
    metrics = run_pipeline(apply_stage=True, record=True, company_slugs=args.company or None)
    print(json.dumps(metrics, indent=2))
    return 0


def cmd_apply(args) -> int:
    from jobbot.runner import apply_pending

    metrics = apply_pending(limit=args.limit, include_failed=False)
    print(json.dumps(metrics, indent=2))
    return 0


def cmd_retry(args) -> int:
    from jobbot.runner import apply_pending

    metrics = apply_pending(limit=args.limit, include_failed=True)
    print(json.dumps(metrics, indent=2))
    return 0


def cmd_status(args) -> int:
    from jobbot.discovery.discover import summarize
    from jobbot.storage.database import Database

    companies = load_companies()
    print(f"Companies: {len(companies)} total, "
          f"{sum(c.is_runnable for c in companies)} runnable, "
          f"{sum(c.discovery_status == DiscoveryStatus.NEEDS_REVIEW for c in companies)} need review, "
          f"{sum(c.discovery_status == DiscoveryStatus.PENDING for c in companies)} pending discovery")
    print("\nProvider distribution (verified):")
    for key, value in sorted(summarize(companies).items(), key=lambda kv: -kv[1]):
        if key != "total":
            print(f"  {key}: {value}")
    db = Database()
    print("\nJobs by status:")
    for status, count in sorted(db.counts_by_status().items()):
        print(f"  {status}: {count}")
    print(f"\nAUTO_APPLY: {auto_apply_enabled()}")
    db.close()
    return 0


def _read_company_names(path: Path) -> list[tuple[str, dict]]:
    """Read (name, extra) pairs from a .txt (one name per line) or .csv file
    with a 'company' column (optional 'rank' column is preserved)."""
    if path.suffix.lower() == ".csv":
        import csv

        out = []
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("company") or row.get("name") or "").strip()
                if not name:
                    continue
                extra = {}
                if row.get("rank"):
                    extra["rank"] = int(row["rank"])
                out.append((name, extra))
        return out
    return [
        (line.strip(), {})
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def cmd_import_companies(args) -> int:
    """Import company names from a .txt or .csv file as pending registry entries."""
    path = Path(args.file)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    companies = [] if args.replace else load_companies()
    existing = {c.slug: c for c in load_companies()}
    known = {c.slug for c in companies}
    added = 0
    for name, extra in _read_company_names(path):
        slug = _slugify(name)
        if slug in known:
            continue
        if args.replace and slug in existing:
            company = existing[slug]  # keep any verified discovery data
            company.extra.update(extra)
        else:
            company = Company(name=name, slug=slug, extra=extra)
        companies.append(company)
        known.add(slug)
        added += 1
    save_companies(companies)
    print(f"added {added} companies ({len(companies)} total)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobbot", description="Personal new-grad SWE job hunter")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="discover careers sources / ATS providers")
    p.add_argument("--limit", type=int, help="max companies to process")
    p.add_argument("--rediscover", action="store_true", help="also re-check verified companies")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("validate-companies", help="verify configured sources still work")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("scan", help="fetch + filter jobs without applying")
    p.add_argument("--dry-run", action="store_true", help="don't write to the database or sheet")
    p.add_argument("--company", action="append", help="limit to a company slug (repeatable)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("run", help="full recurring run (fetch, filter, record, apply)")
    p.add_argument("--company", action="append", help="limit to a company slug (repeatable)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("apply", help="attempt applications for pending eligible jobs")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("retry", help="retry eligible + previously failed applications")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_retry)

    p = sub.add_parser("status", help="show registry / job / application health")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("import-companies", help="import company names from a .txt or .csv file")
    p.add_argument("file")
    p.add_argument("--replace", action="store_true",
                   help="rebuild the registry from this file (verified configs for matching slugs are kept)")
    p.set_defaults(func=cmd_import_companies)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
