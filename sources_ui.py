"""Streamlit source workspace. All queue changes require explicit review."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import streamlit as st

from company_sources import DirectoryMapping, read_directory_file, map_directory, merge_directory, suggest_directory_mapping
from core import Company, Opportunity, EMAIL
from job_research import fetch_public_posting, posting_suggestion
from sheets_client import SheetsReader, spreadsheet_reference


def column_letter(index):
    result = ""
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def render_sources(store, companies, *, disabled=False, expanded=False):
    with st.expander("Company sources & opportunities", expanded=expanded or st.query_params.get("sources") == "1"):
        st.caption("Read a directory, review its contacts, then add them to your queue. Research stays separate from email sending.")
        directory, research = st.tabs(["Directory import", "Roles & tech stacks"])
        with directory:
            mode = st.radio("Directory source", ["Google Sheets", "Upload Excel / CSV"], horizontal=True,
                            disabled=disabled, key="directory_source_mode")
            if mode == "Google Sheets":
                _google_source(disabled)
            else:
                _uploaded_source(disabled)
            staged = st.session_state.get("directory_matrix")
            if staged and staged["mode"] == mode:
                _directory_review(store, companies, staged, disabled)
        with research:
            _research(store, companies, disabled)


def _google_source(disabled):
    st.caption("Uses read-only Google Sheets access. Gmail sign-in does not connect this directory.")
    url = st.text_input("Google spreadsheet URL", value=os.getenv("SHEETS_URL", ""), disabled=disabled,
                        key="directory_url")
    st.code(".\\.venv\\Scripts\\python.exe sheets_client.py auth", language="powershell")
    st.caption("Enable Google Sheets API and set SHEETS_CLIENT_FILE in .env to a Desktop app OAuth client (an existing Desktop client can be reused). Run the command in a terminal on this computer and sign in with the account that can view the sheet.")
    reader = SheetsReader()
    if st.button("Connect / list worksheets", disabled=disabled or not url):
        try:
            tabs = reader.worksheets(url)
            if not tabs:
                raise ValueError("No worksheets found")
            st.session_state.directory_tabs = {"url": url, "tabs": tabs}
            st.session_state.pop("directory_matrix", None)
            _, gid = spreadsheet_reference(url)
            st.session_state.directory_tab_title = next((t["title"] for t in tabs if t["sheetId"] == gid), tabs[0]["title"])
        except Exception as exc:
            st.session_state.pop("directory_tabs", None)
            st.session_state.pop("directory_matrix", None)
            st.error(f"Cannot read Sheets ({type(exc).__name__}). Check sign-in, Sheets API, and file access. If this is an XLSX file, use Upload Excel / CSV or a permitted Google Sheets copy.")
    saved = st.session_state.get("directory_tabs", {})
    if saved.get("url") == url:
        title = st.selectbox("Source worksheet", [t["title"] for t in saved["tabs"]],
                             key="directory_tab_title", disabled=disabled)
        if st.button("Read worksheet", disabled=disabled):
            try:
                with st.spinner("Reading directory…"):
                    rows = reader.read(url, title)
                st.session_state.directory_matrix = {"mode": "Google Sheets", "rows": rows,
                    "source": f"{url.split('#')[0]} | {title}", "url": url, "title": title}
            except Exception as exc:
                st.session_state.pop("directory_matrix", None)
                st.error(f"Worksheet could not be read ({type(exc).__name__}). Verify permissions and that the source is a native Google Sheet.")
        staged = st.session_state.get("directory_matrix", {})
        if staged and (staged.get("url") != url or staged.get("title") != title):
            st.session_state.pop("directory_matrix", None)
    elif st.session_state.get("directory_matrix", {}).get("mode") == "Google Sheets":
        st.session_state.pop("directory_matrix", None)


def _uploaded_source(disabled):
    uploaded = st.file_uploader("Directory workbook or CSV", type=["xlsx", "csv"], disabled=disabled,
                                key="directory_upload", help="Up to 10 MB, 5,000 rows, 52 columns. Formulas are not executed.")
    if uploaded is None:
        if st.session_state.get("directory_matrix", {}).get("mode") == "Upload Excel / CSV":
            st.session_state.pop("directory_matrix", None)
        return
    try:
        raw = uploaded.getvalue()
        names, rows = read_directory_file(raw, uploaded.name)
        title = st.selectbox("Workbook worksheet", names, disabled=disabled)
        if len(names) > 1:
            _, rows = read_directory_file(raw, uploaded.name, title)
        st.session_state.directory_matrix = {"mode": "Upload Excel / CSV", "rows": rows,
            "source": f"Uploaded: {uploaded.name} | {title}", "title": title, "digest": hashlib.sha256(raw).hexdigest()}
    except Exception as exc:
        st.session_state.pop("directory_matrix", None)
        st.error(f"Directory could not be loaded: {exc}")


def _directory_review(store, companies, staged, disabled):
    rows = staged["rows"]
    if not rows:
        st.info("This worksheet is empty")
        return
    fingerprint = hashlib.sha256(("mapping-v2" + json.dumps(staged, sort_keys=True)).encode()).hexdigest()[:16]
    width = max(len(row) for row in rows)
    if not width:
        st.info("No values found")
        return
    columns = list(range(min(width, 52)))
    def label(index):
        if index is None:
            return "Not mapped"
        sample = " / ".join(str(row[index])[:45] for row in rows[:3] if index < len(row) and row[index])
        return f"{column_letter(index)} · {sample or 'No header'}"
    defaults = suggest_directory_mapping(rows)
    st.caption(f"Suggested from worksheet headers: company {column_letter(defaults.company)}, contact {column_letter(defaults.contact)}, position {column_letter(defaults.position)}, email {column_letter(defaults.email)}. Check the source rows before importing. You can choose a POC email column instead of generic HR email.")
    with st.expander("Source rows (first 8)"):
        st.dataframe([{column_letter(i): str(row[i]) if i < len(row) else "" for i in columns}
                      for row in rows[:8]], hide_index=True)
    first = st.number_input("First data row", min_value=1, max_value=5000, value=min(4, len(rows)),
                            step=1, key=f"first_{fingerprint}", disabled=disabled)
    mapped = {}
    for field, title, default, optional in (("company", "Company column", 1, False),
            ("contact", "POC name column", defaults.contact, False), ("position", "POC position column", defaults.position, False),
            ("email", "POC email column", defaults.email, False), ("industry", "Industry column", 2, True),
            ("address", "Address column", 3, True)):
        options = ([None] if optional else []) + columns
        chosen = default if default in columns else (None if optional else columns[0])
        mapped[field] = st.selectbox(title, options, index=options.index(chosen), format_func=label,
                                    key=f"mapping_{fingerprint}_{field}", disabled=disabled)
    fallback_email = defaults.fallback_email if mapped["email"] == defaults.email else None
    if fallback_email is not None:
        st.caption(f"When the selected generic HR email is blank, use POC email {column_letter(fallback_email)} from the same row. Invalid nonempty addresses still need correction.")
    candidates = map_directory(rows, DirectoryMapping(first_data_row=int(first), fallback_email=fallback_email, **mapped), staged["source"])
    digest = hashlib.sha256(json.dumps(candidates, sort_keys=True).encode()).hexdigest()[:16]
    if not candidates:
        st.info("No company rows found for this mapping")
        return
    active_import = staged.get("title", "").strip().upper() == "ACTIVE INDUSTRY PARTNERS"
    st.caption("Check Include for the contacts to add. Blank or invalid emails start unchecked; fix them before importing. Existing email addresses reuse their queue records, preserving statuses and edits. Different HR addresses remain separate contacts.")
    if active_import and staged.get("url"):
        st.caption("Adding reviewed contacts also refreshes Active partners only from this worksheet. General Masterlist contacts remain in your queue.")
    rows_key = f"directory_review_rows_{digest}"
    version_key = f"directory_review_version_{digest}"
    base = st.session_state.get(rows_key, candidates)
    version = st.session_state.get(version_key, 0)
    editor_key = f"directory_review_{digest}_{version}"
    select_col, clear_col = st.columns(2)
    select_all = select_col.button("Select all valid contacts", key=f"directory_select_{digest}", disabled=disabled)
    clear_all = clear_col.button("Clear selection", key=f"directory_clear_{digest}", disabled=disabled)
    if select_all or clear_all:
        # Keep inline edits, including a just-corrected email, when rebuilding the selection.
        base = [dict(row) for row in base]
        for index, changes in st.session_state.get(editor_key, {}).get("edited_rows", {}).items():
            if 0 <= int(index) < len(base):
                base[int(index)].update(changes)
        for row in base:
            row["include"] = bool(select_all and EMAIL.fullmatch(str(row.get("hr_email", "")).strip()))
        st.session_state[rows_key] = base
        version += 1
        st.session_state[version_key] = version
        editor_key = f"directory_review_{digest}_{version}"
    edited = st.data_editor(base, key=editor_key, hide_index=True,
        disabled=True if disabled else ["directory_source", "source_row"], num_rows="fixed", width="stretch")
    if st.button("Add reviewed contacts to queue", type="primary", disabled=disabled):
        try:
            updated, added, skipped = merge_directory(companies, list(edited))
            if not added and not skipped:
                raise ValueError("Check Include on at least one contact")
            snapshot = None
            if active_import and staged.get("url"):
                from active_partners import build_active_list, save_active_list
                snapshot = build_active_list(rows, source_url=staged["url"], worksheet=staged["title"],
                    first_data_row=int(first), company_column=mapped["company"])
            store.replace(updated, companies)
            active_note = ""
            if snapshot is not None:
                try:
                    save_active_list(store.path.parent / ".local" / "active-partners.json", snapshot)
                    active_note = " Active-partner filter refreshed."
                except OSError:
                    active_note = " Contacts saved, but the active-list file could not be updated; refresh it in Company queue."
            st.session_state.pop("confirmation_job", None)
            st.session_state.sources_notice = f"Added {added} contacts; reused {skipped} existing addresses.{active_note} No emails were created or sent."
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(f"Import not saved: {exc}")


def _research(store, companies, disabled):
    if not companies:
        st.info("Import or add a company first to save roles and tech stacks")
        return
    by_id = {c.id: c for c in companies}
    identity = st.selectbox("Research company / POC", list(by_id), key="research_company",
        format_func=lambda key: f"{by_id[key].company_name} · {by_id[key].hr_email}", disabled=disabled)
    company = by_id[identity]
    if company.directory_source:
        st.caption(f"Directory: {company.directory_source} · Row {company.source_row} · POC role: {company.contact_position or 'Unknown'}")
    for i, opportunity in enumerate(company.opportunities):
        with st.expander(f"{opportunity.title} · {opportunity.verification}"):
            st.write("Technologies mentioned: " + (", ".join(opportunity.technologies) or "Unknown"))
            st.link_button("Open posting source", opportunity.source_url)
            st.caption(f"Checked {opportunity.checked_at} · Posted {opportunity.posting_date or 'Unknown'} · Expires {opportunity.expires or 'Unknown'}")
            st.text(opportunity.notes)
            if st.button("Remove saved posting", key=f"remove_posting_{identity}_{i}", disabled=disabled):
                replacement = company.model_copy(update={"opportunities": [o for j, o in enumerate(company.opportunities) if j != i]})
                try:
                    store.replace([replacement if c.id == identity else c for c in companies], companies)
                    st.session_state.pop("confirmation_job", None)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(f"Posting not removed: {exc}")
    url = st.text_input("Job posting URL", key="posting_url", disabled=disabled,
                        placeholder="https://company.example/careers/software-intern")
    text = st.text_area("Posting text (paste for LinkedIn / JobStreet or pages that block fetching)",
                        key="posting_text", disabled=disabled, height=140)
    st.caption("The reader suggests a title and technology mentions. It cannot confirm a vacancy is still open or that every mention is required. Applicant skills and the email template remain under your control.")
    if st.button("Read posting & suggest details", disabled=disabled or not url):
        st.session_state.pop("posting_suggestion", None)
        try:
            if text.strip():
                suggestion = posting_suggestion(text, url)
            else:
                with st.spinner("Reading public posting…"):
                    content, final_url = fetch_public_posting(url)
                suggestion = posting_suggestion(content, final_url, is_html=True)
            st.session_state.posting_suggestion = {"company_id": identity, "input_url": url, "input_text": text,
                                                   "opportunity": suggestion.model_dump()}
            # Reset review widgets only on an explicitly requested fresh read.
            st.session_state.posting_title_review = suggestion.title
            st.session_state.posting_tech_review = ", ".join(suggestion.technologies)
            st.session_state.posting_notes_review = suggestion.notes
            st.session_state.posting_reviewed = False
        except Exception as exc:
            st.error(f"Cannot read posting: {exc}")
    staged = st.session_state.get("posting_suggestion", {})
    if staged.get("company_id") == identity and staged.get("input_url") == url and staged.get("input_text") == text:
        title = st.text_input("Role title (review / edit)", key="posting_title_review", disabled=disabled)
        tech = st.text_input("Technologies mentioned (comma-separated; review / edit)", key="posting_tech_review", disabled=disabled)
        notes = st.text_area("Research notes", key="posting_notes_review", disabled=disabled)
        reviewed = st.checkbox("I checked the source, company match, and role details", key="posting_reviewed", disabled=disabled)
        if st.button("Save reviewed posting", type="primary", disabled=disabled or not reviewed):
            try:
                opportunity = Opportunity.model_validate({**staged["opportunity"], "title": title.strip(),
                    "technologies": list(dict.fromkeys(t.strip() for t in tech.split(",") if t.strip())),
                    "notes": notes, "verification": "reviewed"})
                # Updating the same source replaces its previous research snapshot, not mail state.
                opportunities = [o for o in company.opportunities if o.source_url != opportunity.source_url] + [opportunity]
                replacement = Company.model_validate({**company.model_dump(), "opportunities": opportunities})
                store.replace([replacement if c.id == identity else c for c in companies], companies)
                st.session_state.pop("posting_suggestion", None)
                st.session_state.pop("confirmation_job", None)
                st.session_state.sources_notice = "Saved reviewed posting. Email skills and application status were preserved."
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(f"Posting not saved: {exc}")
