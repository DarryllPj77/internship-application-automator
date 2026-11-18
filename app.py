"""Run locally: python -m streamlit run app.py"""
from __future__ import annotations

import asyncio
import html
import os
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core import (CC, SUBJECT, FIELDS, PLACEHOLDER, Company, CompanyStore,
                  atomic_text, email_payload, import_companies, render_template,
                  run_batch, validate_pdf)
from mcp_client import GmailMCPClient

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
STORE = CompanyStore(ROOT / "companies.json")
TEMPLATE = ROOT / "template.txt"

st.set_page_config(page_title="Internship Desk · Darryll Pajaganas", page_icon="✉️", layout="wide")
st.markdown("""<style>
.block-container {max-width:1600px; padding-top:4rem}
h1 {letter-spacing:-1.4px} h3 {letter-spacing:-.5px}
[data-testid="stMetric"] {background:white;border:1px solid #e0e7eb;border-radius:12px;padding:16px}
.eyebrow {color:#0f766e;font-size:12px;font-weight:700;letter-spacing:2px}
.email-body {white-space:pre-wrap;overflow-wrap:anywhere;background:#fff;border:1px solid #dce5e8;
border-radius:10px;padding:20px;font:14px/1.7 system-ui;color:#172b3a}
.missing {color:#b91c1c;background:#fee2e2;font-weight:700}
</style>""", unsafe_allow_html=True)


def async_run(coroutine):
    # Streamlit script threads on Windows need subprocess-capable Proactor loops.
    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop if os.name == "nt" else None) as runner:
        return runner.run(coroutine)


def reload_table():
    st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1
    st.rerun()


def dismiss_confirmation():
    st.session_state.pop("confirmation_job", None)


@st.dialog("Confirm application batch", width="large", on_dismiss=dismiss_confirmation)
def confirm_batch(job):
    verb = "Send emails" if job["mode"] == "send" else "Create Gmail drafts"
    st.write(f"**{verb} for {len(job['companies'])} selected companies?**")
    st.caption(f"CC on every email: {CC}")
    st.write(f"Attachment: **{Path(job['cv_path']).name}**")
    st.write("Subject: " + SUBJECT)
    st.dataframe([{"Company": c.company_name, "To": c.hr_email, "Current status": c.status.title()}
                  for c in job["companies"]], hide_index=True, width="stretch")
    if any(c.status == "sent" for c in job["companies"]):
        st.warning("You explicitly selected previously sent applications. This batch will process them again.")
    with st.expander("Review every rendered email"):
        for company in job["companies"]:
            st.markdown(f"**{company.company_name}**")
            st.text(render_template(job["template"], company))
    acknowledged = st.checkbox("I reviewed these recipients, bodies, CC, attachment, and the Gmail account used during OAuth.")
    if job["mode"] == "send":
        st.warning("Send Mode delivers immediately. Sent emails cannot be recalled here.")
    if st.button("Confirm and start", type="primary", disabled=not acknowledged):
        st.session_state.pending_job = job
        st.session_state.pop("confirmation_job", None)
        st.rerun()


def main():
    st.markdown('<div class="eyebrow">FEU TECH · INTERNSHIP 1 · 2TSY2627</div>', unsafe_allow_html=True)
    st.title("Your next chapter starts here.")
    st.caption("INTERNSHIP DESK / Darryll Pajaganas · Application workspace")
    try:
        companies = STORE.load()
    except Exception as exc:
        st.error(f"Cannot load companies.json: {exc}. Fix the file before continuing.")
        st.stop()
    job_running = "pending_job" in st.session_state
    with st.container(border=True):
        connection_col, path_col, mode_col = st.columns([1.1, 2, 1.4], gap="large")
        with connection_col:
            st.markdown("**Gmail MCP**")
            status = st.session_state.get("mcp_connected", False)
            st.markdown(":green[● Connected]" if status else ":gray[● Disconnected]")
            st.caption("Status reflects the last session test; each batch reconnects.")
            if st.button("Test MCP Connection", disabled=job_running):
                try:
                    with st.spinner("Starting server and discovering tools…"):
                        capabilities = async_run(GmailMCPClient().test_connection())
                    st.session_state.mcp_connected = True
                    st.session_state.capabilities = capabilities
                    st.rerun()
                except Exception as exc:
                    st.session_state.mcp_connected = False
                    st.error(str(exc))
            if "capabilities" in st.session_state:
                with st.expander("Discovered tools"):
                    st.json(st.session_state.capabilities)
            st.caption("Discovery checks transport/tools; it does not verify token validity or sender identity.")
        with path_col:
            cv_path = st.text_input("PDF CV path", value=os.getenv("CV_FILE_PATH", ""), disabled=job_running)
            try:
                pdf = validate_pdf(cv_path)
                st.success(f"Valid PDF Found · {pdf.name}")
                pdf_valid = True
            except (ValueError, OSError) as exc:
                st.error(f"File Missing / Invalid PDF · {exc}")
                pdf_valid = False
        with mode_col:
            sending = st.toggle("Send Mode (Direct Send)", value=False, disabled=job_running)
            mode = "send" if sending else "draft"
            if sending:
                st.warning("Direct send · 15–30s between emails")
            else:
                st.success("Draft Mode (Safe - Creates Gmail Drafts)")
    counters = st.columns(4)
    for column, status in zip(counters, ("pending", "drafted", "sent", "failed")):
        column.metric(status.title(), sum(c.status == status for c in companies))

    left, right = st.columns([1.12, 1], gap="large")
    with left:
        st.subheader("01 / Target companies")
        st.caption("Edits save automatically. Check Select to include a company; sent rows start unchecked.")
        if st.button("Select all pending", disabled=job_running):
            st.session_state.selected_ids = [c.id for c in companies if c.status == "pending" and not c.needs_review]
            reload_table()
        selected_ids = st.session_state.get("selected_ids", [])
        records = [{"Select": c.id in selected_ids, "id": c.id,
                    **{key: getattr(c, key) for key in FIELDS},
                    "status": {"pending": "⚪ Pending", "drafted": "🔵 Drafted", "sent": "🟢 Sent", "failed": "🔴 Failed"}[c.status],
                    "Review": "⚠ Check Gmail" if c.needs_review else ""} for c in companies]
        editor_key = f"companies_editor_{st.session_state.get('editor_version', 0)}"
        edited = st.data_editor(records, key=editor_key, hide_index=True, width="stretch",
            disabled=True if job_running else ["id", "status", "Review"],
            column_order=["Select", "status", *FIELDS, "Review"],
            column_config={"id": None, "Select": st.column_config.CheckboxColumn("Select", default=False),
                "company_name": st.column_config.TextColumn("Company", required=True),
                "hr_email": st.column_config.TextColumn("HR email", required=True),
                "contact_person": st.column_config.TextColumn("Contact", required=True),
                "relevant_skills": st.column_config.TextColumn("Relevant skills", required=True),
                "status": st.column_config.TextColumn("Status ●", help="Automatically updated after Gmail operations")})
        selected = []
        try:
            replacements = []
            for original, row in zip(companies, edited):
                replacements.append(Company.model_validate({**original.model_dump(), **{key: row[key] for key in FIELDS}}))
                if row["Select"]:
                    selected.append(replacements[-1])
            st.session_state.selected_ids = [c.id for c in selected]
            if replacements != companies:
                STORE.replace(replacements, companies)
                companies = replacements
                st.toast("Company edits saved")
        except Exception as exc:
            st.error(f"Edits not saved: {exc}")
            selected = []
        st.caption(f"{len(selected)} selected · {len(companies)} companies · saved to companies.json")
        with st.expander("＋ Add Company"):
            with st.form("add_company", clear_on_submit=True):
                name = st.text_input("Company name")
                email = st.text_input("HR email")
                contact = st.text_input("Contact person", value="Hiring Team")
                skills = st.text_input("Relevant skills")
                if st.form_submit_button("Add Company", disabled=job_running):
                    try:
                        company = Company(company_name=name, hr_email=email, contact_person=contact, relevant_skills=skills)
                        if any(c.hr_email.casefold() == company.hr_email.casefold() for c in companies):
                            raise ValueError("This HR email already exists")
                        STORE.replace([*companies, company], companies)
                        reload_table()
                    except Exception as exc:
                        st.error(str(exc))
        with st.expander("↑ CSV / JSON Bulk Import"):
            uploaded = st.file_uploader("Choose UTF-8 CSV or JSON", type=["csv", "json"], disabled=job_running)
            st.caption("Columns: company_name, hr_email, contact_person, relevant_skills. New rows start Pending; duplicate emails are skipped.")
            if st.button("Import companies", disabled=uploaded is None or job_running):
                try:
                    imported = import_companies(uploaded.getvalue(), uploaded.name, companies)
                    STORE.replace(imported, companies)
                    reload_table()
                except Exception as exc:
                    st.error(f"Import rejected; no rows changed: {exc}")
        review_rows = [c for c in companies if c.needs_review]
        if review_rows:
            with st.expander("⚠ Review interrupted / failed operations", expanded=True):
                st.warning("Check Gmail Drafts and Sent before retrying. The previous operation may have succeeded.")
                row = st.selectbox("Application to reconcile", review_rows, format_func=lambda c: c.company_name)
                st.text(row.last_result)
                outcome = st.selectbox("Verified Gmail outcome", ["sent", "drafted", "failed"])
                checked = st.checkbox("I checked Gmail and verified this outcome")
                if st.button("Save verified outcome", disabled=not checked or job_running):
                    try:
                        reconciled = [Company.model_validate({**c.model_dump(), "status": outcome,
                            "needs_review": False, "last_result": "Manually reconciled after checking Gmail"})
                            if c.id == row.id else c for c in companies]
                        STORE.replace(reconciled, companies)
                        st.session_state.selected_ids = []
                        reload_table()
                    except Exception as exc:
                        st.error(str(exc))

    with right:
        st.subheader("02 / Write & preview")
        if "template_body" not in st.session_state:
            st.session_state.template_body = TEMPLATE.read_text(encoding="utf-8")
        chip_columns = st.columns(3)
        for column, field in zip(chip_columns, ("contact_person", "company_name", "relevant_skills")):
            def append_chip(field=field):
                st.session_state.template_body += "{" + field + "}"
            column.button("{" + field + "}", on_click=append_chip, width="stretch", disabled=job_running)
        st.caption("Click a placeholder to append it to the template.")
        template = st.text_area("Email template", key="template_body", height=330, disabled=job_running)
        if template != TEMPLATE.read_text(encoding="utf-8") and not job_running:
            try:
                atomic_text(TEMPLATE, template)
                st.caption("Template saved automatically")
            except OSError as exc:
                st.error(f"Template not saved: {exc}")
        st.markdown("**Live email preview**")
        if companies:
            preview = st.selectbox("Preview company", companies, format_func=lambda c: f"{c.company_name} · {c.hr_email}")
            body = render_template(template, preview)
            st.text(f"To: {preview.hr_email}\nCC: {CC}\nSubject: {SUBJECT}\nAttachment: {Path(cv_path).name if cv_path else 'No PDF selected'}")
            highlighted = PLACEHOLDER.sub(lambda m: '<span class="missing">' + m.group() + '</span>', html.escape(body))
            st.markdown('<div class="email-body">' + highlighted.replace("\n", "<br>") + '</div>', unsafe_allow_html=True)
            if "{" in body or "}" in body:
                st.error("Missing/unreplaced placeholders or stray braces. Execution is blocked.")
        else:
            st.info("Add a company to preview your application.")

    st.divider()
    st.subheader("03 / Batch activity")
    action = f"Send Emails to Selected ({len(selected)})" if sending else f"Create Drafts for Selected ({len(selected)})"
    if st.button(action, type="primary", disabled=not selected or not pdf_valid or job_running):
        try:
            for company in selected:
                email_payload(company, template, cv_path)
                if company.needs_review:
                    raise ValueError(f"Reconcile {company.company_name} before retrying")
            st.session_state.confirmation_job = {"companies": selected, "template": template, "cv_path": cv_path, "mode": mode}
        except Exception as exc:
            st.error(str(exc))
    if "confirmation_job" in st.session_state:
        confirm_batch(st.session_state.confirmation_job)
    progress = st.progress(0, text="Ready when you are")
    countdown = st.empty()
    console = st.empty()
    logs = st.session_state.setdefault("activity_logs", [])
    console.code("\n".join(logs[-150:]) or "No activity yet. Start with a connection test and a draft.", language="text")
    if job_running:
        job = st.session_state.pop("pending_job")  # consume confirmation exactly once
        def emit(kind, value):
            if kind == "log":
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {value}")
                st.session_state.activity_logs = logs[-150:]
                console.code("\n".join(logs[-150:]), language="text")
            elif kind == "progress":
                progress.progress(value, text=f"Processed {int(value * len(job['companies']))} / {len(job['companies'])}")
            elif kind == "countdown":
                countdown.info(f"Next email in {value}s…") if value else countdown.empty()
        try:
            async_run(run_batch(STORE, GmailMCPClient(), **job, emit=emit))
            emit("log", "Batch finished. Check company statuses for results.")
        except Exception as exc:
            st.session_state.mcp_connected = False
            emit("log", f"Batch stopped: {exc}")
        finally:
            st.session_state.selected_ids = []
        reload_table()
    if logs:
        st.download_button("Download activity log", "\n".join(logs), file_name="internship-activity.txt", mime="text/plain")
    st.caption("Local workspace · Mandatory school CC · Drafts by default · No automatic retries")


if __name__ == "__main__":
    main()
