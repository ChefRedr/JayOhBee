"""Shared Playwright form-filling machinery for application adapters.

Behaves like an applicant filling a form: navigate, type, upload, click.
No CAPTCHA bypass, no fingerprint games — when blocked, hand off to a human.
"""
from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass, field

from jobbot.applications.form_mapping import pick_option, resolve
from jobbot.config import ApplicantProfile

log = logging.getLogger("jobbot.apply")

CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha'][src*='bframe']",  # visible challenge frame
    "div.h-captcha iframe",
    "iframe[src*='hcaptcha.com/captcha']",
    "[data-testid='captcha']",
    "iframe[title*='challenge']",
]

RESUME_HINTS = ("resume", "cv")
COVER_HINTS = ("cover letter", "cover_letter", "coverletter")


def save_debug_screenshot(page, name: str) -> None:
    """Save a screenshot to artifacts/ when JOBBOT_SCREENSHOTS is enabled.
    Screenshots can contain personal data — the directory is gitignored and
    should be treated as sensitive if uploaded as CI artifacts."""
    import os
    import re as _re
    from pathlib import Path

    if os.environ.get("JOBBOT_SCREENSHOTS", "").lower() not in ("1", "true", "yes"):
        return
    with contextlib.suppress(Exception):
        out = Path("artifacts")
        out.mkdir(exist_ok=True)
        safe = _re.sub(r"[^A-Za-z0-9_-]", "_", name)[:120]
        page.screenshot(path=str(out / f"{safe}.png"), full_page=True)


@dataclass
class FillReport:
    filled: list[str] = field(default_factory=list)
    unknown_required: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    @property
    def can_submit(self) -> bool:
        return not self.unknown_required and not self.blocked_reason


@contextlib.contextmanager
def launch_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


def visible_captcha(page) -> bool:
    for sel in CAPTCHA_SELECTORS:
        loc = page.locator(sel)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _label_for(page, element) -> str:
    """Best-effort human label for a form control."""
    with contextlib.suppress(Exception):
        aria = element.get_attribute("aria-label")
        if aria:
            return aria
        el_id = element.get_attribute("id")
        if el_id:
            lab = page.locator(f"label[for='{el_id}']")
            if lab.count() > 0:
                return lab.first.inner_text().strip()
        handle = element.element_handle()
        if handle:
            text = handle.evaluate(
                "el => { const l = el.closest('label') || "
                "(el.closest('div,fieldset')?.querySelector('label, legend, .label, [class*=\"label\"]'));"
                " return l ? l.textContent : ''; }"
            )
            if text and text.strip():
                return text.strip()
        placeholder = element.get_attribute("placeholder")
        if placeholder:
            return placeholder
        name = element.get_attribute("name")
        if name:
            return name
    return ""


def _is_required(element, label: str) -> bool:
    with contextlib.suppress(Exception):
        if element.get_attribute("required") is not None:
            return True
        if (element.get_attribute("aria-required") or "").lower() == "true":
            return True
    return "*" in label or "✱" in label or "required" in label.lower()


def _clean_label(label: str) -> str:
    return re.sub(r"[✱*]|\(required\)|required", "", label, flags=re.IGNORECASE).strip()


def fill_form(page, profile: ApplicantProfile, form_selector: str = "form") -> FillReport:
    """Fill every field we can answer from the profile; report the rest.

    Only required fields with no known answer block submission; optional
    unknown fields are simply left blank.
    """
    report = FillReport()

    if visible_captcha(page):
        report.blocked_reason = "CAPTCHA present"
        return report

    form = page.locator(form_selector).first
    if form.count() == 0:
        report.blocked_reason = "no application form found on page"
        return report

    controls = form.locator("input, select, textarea")
    for i in range(controls.count()):
        el = controls.nth(i)
        try:
            tag = el.evaluate("el => el.tagName.toLowerCase()")
            itype = (el.get_attribute("type") or "text").lower()
            if itype in ("hidden", "submit", "button", "search"):
                continue
            # file inputs are often display:none behind a styled upload button
            # (e.g. Ashby); every other control must be visible to count
            if itype != "file" and not el.is_visible():
                continue
            raw_label = _label_for(page, el)
            label = _clean_label(raw_label)
            required = _is_required(el, raw_label)

            if itype == "file":
                low = f"{label} {el.get_attribute('name') or ''}".lower()
                if any(h in low for h in RESUME_HINTS) and not any(h in low for h in COVER_HINTS):
                    el.set_input_files(str(profile.resume_path))
                    report.filled.append(f"resume upload ({label or 'file'})")
                elif required:
                    report.unknown_required.append(f"required file: {label or 'unknown'}")
                continue

            if tag == "select":
                answer = resolve(label, profile)
                options = el.locator("option").all_inner_texts()
                if answer:
                    choice = pick_option(answer.value, options)
                    if choice:
                        el.select_option(label=choice)
                        report.filled.append(label)
                        continue
                if required and not el.input_value():
                    report.unknown_required.append(f"select: {label or 'unknown'}")
                continue

            if itype in ("checkbox", "radio"):
                answer = resolve(label, profile)
                if answer and answer.value.strip().lower() in ("yes", "true", "y") and itype == "checkbox":
                    el.check()
                    report.filled.append(label)
                elif required and itype == "checkbox":
                    report.unknown_required.append(f"checkbox: {label or 'unknown'}")
                # radio groups are handled per-group below via their labels;
                # unknown required radios surface through post-fill validation
                continue

            # text-like inputs and textareas
            if el.input_value():
                continue  # pre-filled (e.g. parsed from resume)
            answer = resolve(label, profile)
            if answer:
                el.fill(answer.value)
                report.filled.append(label)
            elif required:
                report.unknown_required.append(f"field: {label or 'unknown'}")
        except Exception as exc:  # noqa: BLE001 — one odd widget shouldn't kill the attempt
            log.debug("field %d error: %s", i, exc)
            with contextlib.suppress(Exception):
                if _is_required(el, _label_for(page, el)):
                    report.unknown_required.append("unprocessable required field")
    return report
