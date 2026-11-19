"""Run locally: python -m streamlit run app.py"""
from __future__ import annotations

import asyncio
import html
import os
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core import (SUBJECT, FIELDS, PLACEHOLDER, Company, CompanyEdit, CompanyStore, EmailSettings,
                  atomic_text, email_payload, import_companies, render_template,
                  run_batch, validate_pdf, load_email_settings, save_email_settings, save_uploaded_cv)
from mcp_client import GmailMCPClient
from ui import company_table, preview_metadata, status_pill, stylesheet
from sources_ui import render_sources
from matcher_ui import render_matcher

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
STORE = CompanyStore(ROOT / "companies.json")
TEMPLATE = ROOT / "template.txt"
EMAIL_SETTINGS = ROOT / "email_settings.json"

st.set_page_config(page_title="Internship Desk · Darryll Pajaganas", page_icon=":material/mail:", layout="wide")
st.markdown(stylesheet(), unsafe_allow_html=True)


def async_run(coroutine):
    # Streamlit script threads on Windows need subprocess-capable Proactor loops.
    with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop if os.name == "nt" else None) as runner:
        return runner.run(coroutine)


def reload_table():
    st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1
    st.rerun()


def dismiss_confirmation():
    st.session_state.pop("confirmation_job", None)


def update_uploaded_cv():
    uploaded = st.session_state.get("cv_upload")
    st.session_state.pop("cv_upload_error", None)
    previous = st.session_state.pop("uploaded_cv_path", None)
    if uploaded is None:
        if st.session_state.get("cv_path") == previous:
            st.session_state.cv_path = ""
        return
    try:
        path = save_uploaded_cv(ROOT / "uploads" / "cvs", uploaded.name, uploaded.getvalue())
        st.session_state.cv_path = str(path)
        st.session_state.uploaded_cv_path = str(path)
    except (ValueError, OSError) as exc:
        st.session_state.cv_path = ""
        st.session_state.cv_upload_error = str(exc)


@st.dialog("Confirm application batch", width="large", on_dismiss=dismiss_confirmation)
def confirm_batch(job):
    verb = "Send emails" if job["mode"] == "send" else "Create Gmail drafts"
    st.write(f"**{verb} for {len(job['companies'])} selected companies?**")
    st.text("CC: " + (", ".join(job.get("cc", [])) or "None") +
            "\nBCC: " + (", ".join(job.get("bcc", [])) or "None"))
    st.caption("These copy recipients apply to every email in this batch. BCC is hidden from other recipients.")
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
    acknowledged = st.checkbox("I reviewed To, CC, BCC, bodies, attachment, and the Gmail account used during OAuth.")
    if job["mode"] == "send":
        st.warning("Send Mode delivers immediately. Sent emails cannot be recalled here.")
    if st.button("Confirm and start", type="primary", disabled=not acknowledged):
        st.session_state.pending_job = job
        st.session_state.pop("confirmation_job", None)
        st.rerun()


def main():
    st.markdown('<div class="workspace-header"><div><div class="workspace-title">Internship Desk</div>'
                '<div class="workspace-subtitle">Darryll Pajaganas / Application workspace</div></div>'
                '<div class="workspace-meta">FEU Institute of Technology<br>Internship 1 · 2TSY2627</div></div>', unsafe_allow_html=True)
    with st.container(key="page_heading"):
        st.title("Internship applications", anchor=False)
        st.caption("Manage your company list, personalize each introduction, and review every email before it leaves.")
    try:
        companies = STORE.load()
    except Exception as exc:
        st.error(f"Cannot load companies.json: {exc}. Fix the file before continuing.")
        st.stop()
    job_running = "pending_job" in st.session_state
    try:
        saved_email_settings = load_email_settings(EMAIL_SETTINGS)
    except (ValueError, OSError) as exc:
        st.error(f"Cannot load email_settings.json: {exc}. Fix the settings file before continuing.")
        st.stop()
    with st.container(key="configuration_panel"):
        connection_col, path_col, mode_col = st.columns([1.1, 2, 1.4], gap="small")
        with connection_col:
            st.markdown('<div class="panel-heading">Gmail connection</div>', unsafe_allow_html=True)
            status = st.session_state.get("mcp_connected", False)
            st.markdown(status_pill("sent" if status else "pending", "Connected" if status else "Disconnected"), unsafe_allow_html=True)
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
            st.caption("Last discovery result. Each batch reconnects; the OAuth account determines the sender.")
        with path_col:
            if "cv_path" not in st.session_state:
                st.session_state.cv_path = os.getenv("CV_FILE_PATH", "")
            st.file_uploader("Upload PDF CV", type=["pdf"], key="cv_upload",
                             on_change=update_uploaded_cv, disabled=job_running,
                             help="Choose a PDF up to 20 MB. It is saved locally and selected as your attachment.")
            st.caption("Upload a PDF up to 20 MB, or enter a local path below.")
            if st.session_state.get("cv_upload_error"):
                st.error(st.session_state.cv_upload_error)
            cv_path = st.text_input("PDF CV path", key="cv_path", disabled=job_running)
            try:
                pdf = validate_pdf(cv_path)
                st.markdown(status_pill("sent", "Valid PDF Found"), unsafe_allow_html=True)
                st.caption(pdf.name)
                pdf_valid = True
            except (ValueError, OSError) as exc:
                st.markdown(status_pill("failed", "File Missing / Invalid PDF"), unsafe_allow_html=True)
                st.caption(str(exc))
                pdf_valid = False
        with mode_col:
            sending = st.toggle("Send Mode (Direct Send)", value=False, disabled=job_running)
            mode = "send" if sending else "draft"
            if sending:
                st.markdown(status_pill("drafted", "Send Mode"), unsafe_allow_html=True)
                st.caption("Sends immediately after confirmation. A 15–30s pause separates emails.")
            else:
                st.markdown(status_pill("drafted", "Draft Mode"), unsafe_allow_html=True)
                st.caption("Creates Gmail drafts for your review. Nothing is sent.")
        with st.expander("Optional CC / BCC recipients", expanded=bool(saved_email_settings.cc or saved_email_settings.bcc)):
            st.caption("Applied automatically to every draft or send in a confirmed batch. Leave a field blank to remove its recipients. Separate addresses with commas or semicolons.")
            if "copy_cc" not in st.session_state:
                st.session_state.copy_cc = ", ".join(saved_email_settings.cc)
                st.session_state.copy_bcc = ", ".join(saved_email_settings.bcc)
            cc_text = st.text_input("CC recipients (optional)", key="copy_cc", disabled=job_running,
                                    placeholder="coordinator@example.com, recruiter@example.com")
            bcc_text = st.text_input("BCC recipients (optional)", key="copy_bcc", disabled=job_running,
                                     placeholder="Your private copy address, or leave blank")
            copies_valid = True
            try:
                copy_settings = EmailSettings(cc=cc_text, bcc=bcc_text)
                if copy_settings != saved_email_settings and not job_running:
                    save_email_settings(EMAIL_SETTINGS, copy_settings)
                st.caption("Copy settings saved locally. They do not change existing Gmail drafts.")
            except (ValueError, OSError) as exc:
                copies_valid = False
                copy_settings = EmailSettings()
                st.error(f"Copy settings not saved. Fix CC / BCC before running a batch: {exc}")
    counters = st.columns(4)
    for column, status in zip(counters, ("pending", "drafted", "sent", "failed")):
        with column, st.container(key=f"kpi_{status}"):
            st.markdown(status_pill(status), unsafe_allow_html=True)
            st.metric(status.title(), sum(c.status == status for c in companies), label_visibility="collapsed")

    if notice := st.session_state.pop("sources_notice", None):
        st.success(notice)
    render_sources(STORE, companies, disabled=job_running)
    render_matcher(ROOT, disabled=job_running)

    with st.container(key="workspace_grid"):
        left, right = st.columns([1.4, 1], gap="small")
        with left, st.container(key="companies_panel"):
            st.markdown('<div class="section-label">01 / Company queue</div>', unsafe_allow_html=True)
            st.header("Target companies", anchor=False)
            st.caption("Edit a field to save. Select the companies for your next batch.")
            selected_ids = st.session_state.get("selected_ids", [])
            editor_key = f"companies_editor_{st.session_state.get('editor_version', 0)}"
            event = company_table(companies, selected_ids, disabled=job_running, key=editor_key)
            if event and event.get("action"):
                action = event["action"]
                nonce = action.get("nonce")
                if nonce and nonce != st.session_state.get("last_queue_action"):
                    st.session_state.last_queue_action = nonce
                    try:
                        if job_running:
                            raise ValueError("Wait for the current batch to finish before changing the queue")
                        if event.get("stale"):
                            raise ValueError("The queue changed. Reopen the company action and review it again.")
                        if action.get("type") == "edit":
                            companies = STORE.edit_company(action["id"], CompanyEdit.model_validate(action["changes"]), expected=companies)
                        elif action.get("type") == "delete":
                            companies = STORE.remove_companies(action["ids"], expected=companies)
                        else:
                            raise ValueError("Unknown company action")
                        st.session_state.selected_ids = [identity for identity in event.get("selected_ids", selected_ids) if any(c.id == identity for c in companies)]
                        st.session_state.pop("confirmation_job", None)
                        st.toast("Company queue updated")
                        reload_table()
                    except (ValueError, KeyError, OSError) as exc:
                        st.error(f"Queue change not saved: {exc}")
                event = None
            edited = {row["id"]: row for row in event["rows"]} if event and not job_running else {}
            chosen_ids = set(event["selected_ids"] if event and not job_running else selected_ids)
            selected = []
            try:
                replacements = []
                for original in companies:
                    row = edited.get(original.id, original.model_dump())
                    replacements.append(Company.model_validate({**original.model_dump(), **{key: row[key] for key in FIELDS}}))
                    if original.id in chosen_ids:
                        selected.append(replacements[-1])
                st.session_state.selected_ids = [c.id for c in selected]
                if replacements != companies:
                    STORE.replace(replacements, companies)
                    companies = replacements
                    st.toast("Company edits saved")
            except Exception as exc:
                st.error(f"Edits not saved: {exc}")
                selected = []
            st.caption(f"{len(selected)} selected · {len(companies)} companies · Changes saved automatically")
            with st.expander("Add company"):
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
            with st.expander("CSV / JSON bulk import"):
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

        with right, st.container(key="composer_panel"):
            st.markdown('<div class="section-label">02 / Email workspace</div>', unsafe_allow_html=True)
            st.header("Compose & preview", anchor=False)
            template_tab, preview_tab = st.tabs(["Template", "Email preview"])
            with template_tab:
                if "template_body" not in st.session_state:
                    st.session_state.template_body = TEMPLATE.read_text(encoding="utf-8")
                chip_columns = st.columns(3, gap="small")
                for column, field in zip(chip_columns, ("contact_person", "company_name", "relevant_skills")):
                    def append_chip(field=field):
                        st.session_state.template_body += "{" + field + "}"
                    column.button("{" + field + "}", on_click=append_chip, width="stretch", disabled=job_running)
                st.caption("Insert a placeholder. Each email uses the selected company’s details.")
                template = st.text_area("Email template", key="template_body", height=330, disabled=job_running)
                if template != TEMPLATE.read_text(encoding="utf-8") and not job_running:
                    try:
                        atomic_text(TEMPLATE, template)
                        st.caption("Template saved automatically")
                    except OSError as exc:
                        st.error(f"Template not saved: {exc}")
            with preview_tab:
                st.markdown("**Live email preview**")
                if companies:
                    preview_by_id = {c.id: c for c in companies}
                    if st.session_state.get("preview_company_id") not in preview_by_id:
                        st.session_state.preview_company_id = companies[0].id
                    preview_id = st.selectbox("Preview company", list(preview_by_id), key="preview_company_id",
                                              format_func=lambda identity: f"{preview_by_id[identity].company_name} · {preview_by_id[identity].hr_email}")
                    preview = preview_by_id[preview_id]
                    body = render_template(template, preview)
                    if copies_valid:
                        st.markdown(preview_metadata(preview.hr_email, SUBJECT, Path(cv_path).name if cv_path else "No PDF selected",
                                                     cc=copy_settings.cc, bcc=copy_settings.bcc), unsafe_allow_html=True)
                    else:
                        st.error("Fix the CC / BCC fields to preview the complete recipient list.")
                    highlighted = PLACEHOLDER.sub(lambda m: '<span class="missing">' + m.group() + '</span>', html.escape(body))
                    st.markdown('<div class="email-body">' + highlighted.replace("\n", "<br>") + '</div>', unsafe_allow_html=True)
                    if "{" in body or "}" in body:
                        st.error("Missing/unreplaced placeholders or stray braces. Execution is blocked.")
                else:
                    st.info("Add a company to preview your application.")

    with st.container(key="batch_panel"):
        st.header("Batch activity", anchor=False)
        action = f"Send Emails to Selected ({len(selected)})" if sending else f"Create Drafts for Selected ({len(selected)})"
        if st.button(action, type="primary", disabled=not selected or not pdf_valid or not copies_valid or job_running):
            try:
                for company in selected:
                    email_payload(company, template, cv_path, cc=copy_settings.cc, bcc=copy_settings.bcc)
                    if company.needs_review:
                        raise ValueError(f"Reconcile {company.company_name} before retrying")
                st.session_state.confirmation_job = {"companies": selected, "template": template, "cv_path": cv_path, "mode": mode,
                                                     "cc": list(copy_settings.cc), "bcc": list(copy_settings.bcc)}
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
    st.markdown('<div class="workspace-footer"><span>Local workspace · Drafts by default</span>'
                '<span>Optional copies · Every batch reviewed</span></div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
