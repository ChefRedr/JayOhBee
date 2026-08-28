"""Google Sheets log — the human-facing dashboard. SQLite stays authoritative.

Auth: a service account, provided either as a file path
(GOOGLE_SERVICE_ACCOUNT_FILE) or raw JSON (GOOGLE_SERVICE_ACCOUNT_JSON).
Target spreadsheet: SHEETS_SPREADSHEET_ID. Share the sheet with the service
account's email. If unconfigured, all calls are silent no-ops so the bot
still works locally.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("jobbot.sheets")

HEADER = [
    "Company", "Role", "Location", "Date Found", "Job URL", "Application URL",
    "Provider", "Status", "Applied At", "Needs Review", "Notes",
]
WORKSHEET = "Jobs"


class SheetsLog:
    def __init__(self):
        self._ws = None
        self._enabled = bool(os.environ.get("SHEETS_SPREADSHEET_ID"))

    def _worksheet(self):
        if self._ws is not None:
            return self._ws
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if raw:
            creds = Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
        elif path:
            creds = Credentials.from_service_account_file(path, scopes=scopes)
        else:
            raise RuntimeError("no Google service account configured")
        client = gspread.authorize(creds)
        sheet = client.open_by_key(os.environ["SHEETS_SPREADSHEET_ID"])
        try:
            ws = sheet.worksheet(WORKSHEET)
        except gspread.WorksheetNotFound:
            ws = sheet.add_worksheet(WORKSHEET, rows=2000, cols=len(HEADER))
            ws.append_row(HEADER)
        if not ws.row_values(1):
            ws.append_row(HEADER)
        self._ws = ws
        return ws

    def upsert_job(
        self,
        *,
        company: str,
        title: str,
        location: str | None,
        date_found: str,
        job_url: str,
        apply_url: str,
        provider: str,
        status: str,
        applied_at: str = "",
        needs_review: str = "",
        notes: str = "",
    ) -> None:
        """Insert or update the row for a job, keyed by its job URL."""
        if not self._enabled:
            return
        try:
            ws = self._worksheet()
            row = [
                company, title, location or "", date_found, job_url, apply_url,
                provider, status, applied_at, needs_review, notes,
            ]
            cell = None
            try:
                cell = ws.find(job_url, in_column=5)
            except Exception:  # noqa: BLE001 — gspread raises on not-found in some versions
                cell = None
            if cell:
                ws.update(f"A{cell.row}:K{cell.row}", [row])
            else:
                ws.append_row(row, value_input_option="RAW")
        except Exception as exc:  # noqa: BLE001 — sheet failures must not break the run
            log.error("sheets upsert failed for %s / %s: %s", company, title, exc)
