"""Presentation helpers; mail and persistence rules stay in core.py."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

import streamlit.components.v1 as components

UI_ROOT = Path(__file__).resolve().parent / "ui"
_company_table = components.declare_component("company_table", path=str(UI_ROOT / "company_table"))


def stylesheet() -> str:
    return "<style>" + (UI_ROOT / "dashboard.css").read_text(encoding="utf-8") + "</style>"


def status_pill(status: str, label: str | None = None) -> str:
    if status not in ("pending", "drafted", "sent", "failed"):
        raise ValueError("Unknown presentation status")
    return f'<span class="status-pill status-{status}"><span aria-hidden="true" class="status-dot"></span>{html.escape(label or status.title())}</span>'


def company_table(companies, selected_ids, *, disabled=False, key="company_table"):
    rows = [company.model_dump() for company in companies]
    revision = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    event = _company_table(rows=rows, selected_ids=selected_ids, revision=revision,
                           disabled=disabled, key=key, default=None)
    return event if event and event.get("revision") == revision else None


def preview_metadata(recipient: str, cc: str, subject: str, filename: str) -> str:
    return '<div class="email-envelope">' + "".join(
        f'<div class="envelope-row"><span class="envelope-label">{label}</span>'
        f'<span class="{style}">{html.escape(value)}</span></div>'
        for label, value, style in (("To", recipient, "mono"), ("Cc", cc, "mono"),
                                    ("Subject", subject, "email-subject"),
                                    ("Attachment", filename, "mono"))
    ) + '</div>'
