"""Partner search and explicit, reviewed additions to the target-company queue."""
from __future__ import annotations

import os
import time
from uuid import uuid4
from pathlib import Path

import streamlit as st
from dotenv import dotenv_values

from partner_matcher import (MatcherStore, partner_snapshot, search_links, export_searches,
    BraveSearch, configured_search_key, search_query, leads_from_results, LeadReview, SearchFailure, suggested_search_name)
from search_providers import provider_picker, search_client
from sheets_client import SheetsReader, spreadsheet_reference
from core import CompanyStore
from partner_targets import partner_contacts, add_partner_target
from skills_ui import relevant_skills_picker
from requirements_ui import requirements_finder


def render_matcher(root: Path, *, disabled=False, expanded=False):
    store = MatcherStore(root / ".local" / "partner-jobs.json")
    with st.expander("FEU Partner Job Matcher", expanded=expanded or st.query_params.get("matcher") == "1"):
        st.caption("Find C# / .NET opportunities at companies listed in your FEU directory. Search links work without an API key. A directory entry is not proof of a current partnership or an open internship.")
        try:
            state = store.load()
        except (OSError, ValueError):
            st.error("Cannot read the private matcher data. Restore .local/partner-jobs.json before continuing.")
            return
        notice = st.session_state.pop("matcher_notice", None)
        if notice:
            st.success(notice)
        directory_tab, results_tab, settings_tab = st.tabs(["Partner directory & search links", "Discovered postings", "Discovery setup"])
        with directory_tab:
            _directory(root, store, state, disabled)
        with results_tab:
            _postings(root, store, state, disabled)
        with settings_tab:
            _setup(root)


def _directory(root, store, state, disabled):
    default_url = dotenv_values(root / ".env").get("SHEETS_URL") or os.getenv("SHEETS_URL", "")
    url = st.text_input("Partner directory spreadsheet URL", value=default_url, key="matcher_source_url", disabled=disabled)
    if st.button("Load worksheets for matching", disabled=disabled or not url):
        try:
            reader = SheetsReader()
            tabs = reader.worksheets(url)
            if not tabs:
                raise ValueError("No worksheets found")
            st.session_state.matcher_tabs = {"url": url, "tabs": tabs}
            _, gid = spreadsheet_reference(url)
            st.session_state.matcher_tab = next((t["title"] for t in tabs if t["sheetId"] == gid), tabs[0]["title"])
        except Exception as exc:
            st.session_state.pop("matcher_tabs", None)
            st.error(f"Cannot read this directory ({type(exc).__name__}). Check the Sheets connection and use a native Google Sheets copy.")
    loaded = st.session_state.get("matcher_tabs", {})
    if loaded.get("url") == url:
        title = st.selectbox("Partner worksheet", [t["title"] for t in loaded["tabs"]], key="matcher_tab", disabled=disabled)
        st.caption("Choose the source tab that defines your partner list. The masterlist and active-partner tabs may contain different companies; the selected source is retained with the results.")
        first = st.number_input("Matcher: first company data row", min_value=1, max_value=5000, value=4, step=1, disabled=disabled)
        column = st.selectbox("Matcher: company-name column", list(range(26)), index=1,
                              format_func=lambda i: chr(65 + i), disabled=disabled)
        st.caption("For GENERAL MASTERLIST, use row 4 and column B. Existing research is retained when reloading the same snapshot. Other directory versions are archived locally.")
        if st.button("Load partner companies & build search links", type="primary", disabled=disabled):
            try:
                with st.spinner("Reading partner names…"):
                    rows = SheetsReader().read(url, title)
                snapshot = partner_snapshot(rows, source_url=url, worksheet=title,
                                            first_data_row=int(first), company_column=column)
                store.set_directory(snapshot)
                st.session_state.matcher_notice = f"Loaded {len(snapshot['partners'])} unique partner names. Search links are ready; no emails were created or sent."
                st.rerun()
            except Exception as exc:
                st.error(f"Partner directory not updated ({type(exc).__name__}). Check the source and mapping.")
    directory = state.get("directory")
    if not directory:
        st.info("Load the partner names directly from your spreadsheet. You do not need to import HR contacts into the email queue first.")
        return
    st.caption(f"Loaded source: {directory['worksheet']} · {len(directory['partners'])} companies · Read {directory['checked_at']}")
    st.link_button("Open directory source", directory["source_url"])
    location = st.text_input("Search location", value="Philippines", key="matcher_location", max_chars=100)
    name_filter = st.text_input("Filter partner names", key="matcher_company_filter")
    partners = [p for p in directory["partners"] if name_filter.casefold() in p["name"].casefold()]
    search_names = state.get("search_names", {})
    with st.expander("Adjust a company's search name"):
        if not partners:
            st.caption("No companies match your filter. Change or clear it to adjust a search name.")
        else:
            by_id = {p["id"]: p for p in partners}
            if st.session_state.get("matcher_adjust_partner") not in by_id:
                st.session_state.matcher_adjust_partner = next(iter(by_id))
            identity = st.selectbox("Company to adjust", list(by_id), format_func=lambda k: by_id[k]["name"],
                                    key="matcher_adjust_partner", disabled=disabled)
            partner = by_id[identity]
            with st.form(f"search_name_{identity}"):
                query_name = st.text_input("Job-board search name", value=search_names.get(identity, suggested_search_name(partner["name"])), max_chars=200, disabled=disabled)
                st.caption("Use the employer's searchable brand name. This only broadens discovery; it does not establish that another employer is the same FEU partner.")
                if st.form_submit_button("Save search name", disabled=disabled):
                    try:
                        store.set_search_name(directory["revision"], identity, query_name)
                        st.session_state.matcher_notice = "Updated search links. The original directory name and employer-verification rules were preserved."
                        st.rerun()
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
    st.caption("These links search by company name only, without added technology keywords. They are not verified vacancies. On narrow screens, scroll the table horizontally to reach the links.")
    st.caption("Search names omit legal suffixes and directory markers. Job boards may show broader results; always check the employer on each posting.")
    rows = [{"Company": p["name"], "Search name": search_names.get(p["id"], suggested_search_name(p["name"])), "Directory rows": ", ".join(map(str, p["source_rows"])),
             **search_links(p["name"], location, search_name=search_names.get(p["id"]))} for p in partners]
    st.dataframe(rows, hide_index=True, width="stretch", height=min(400, 40 + 35 * max(1, len(rows))),
        column_config={"Indeed search": st.column_config.LinkColumn("Indeed search", display_text="Search Indeed"),
                       "JobStreet search": st.column_config.LinkColumn("JobStreet search", display_text="Search JobStreet")})
    _target_company(root, store, directory, partners, disabled)
    st.download_button("Download all partner search links (CSV)", export_searches(directory["partners"], location, search_names),
                       file_name="feu-partner-job-searches.csv", mime="text/csv")
    st.caption(f"Showing {len(partners)} of {len(directory['partners'])} partners. The download includes company-name searches for all partners on both boards.")


def _target_company(root, matcher_store, directory, partners, disabled):
    st.markdown("**Add a searched partner to Target Companies**")
    if not partners:
        st.caption("Filter the directory to a company you want to add.")
        return
    queue = CompanyStore(root / "companies.json")
    locked = disabled or queue.batch_lock.exists()
    by_id = {p["id"]: p for p in partners}
    if st.session_state.get("matcher_target_partner") not in by_id:
        st.session_state.matcher_target_partner = next(iter(by_id))
    identity = st.selectbox("Partner to add", list(by_id), format_func=lambda k: by_id[k]["name"],
                            key="matcher_target_partner", disabled=locked)
    reviewed = requirements_finder(root, "partner_requirements_" + identity, by_id[identity]["name"],
        search_name=matcher_store.load().get("search_names", {}).get(identity, ""), disabled=locked)
    if reviewed:
        st.session_state["partner_requirements_choice_" + identity] = reviewed
    if st.button("Add to Target Companies", type="primary", disabled=locked):
        try:
            with st.spinner("Loading the partner's current contacts…"):
                rows = SheetsReader().read(directory["source_url"], directory["worksheet"])
            contacts = partner_contacts(rows, directory, identity)
            error = ""
        except Exception as exc:
            contacts = []
            error = f"Contacts could not be loaded ({type(exc).__name__}). Check Sheets access or enter a verified recipient manually."
        st.session_state.matcher_target_draft = {"partner_id": identity, "revision": directory["revision"],
            "contacts": contacts, "error": error, "nonce": uuid4().hex}
        st.session_state.pop("confirmation_job", None)
    draft = st.session_state.get("matcher_target_draft", {})
    if draft.get("partner_id") != identity or draft.get("revision") != directory["revision"]:
        return
    if draft["error"]:
        st.warning(draft["error"])
    contacts = draft["contacts"]
    if not contacts and not draft["error"]:
        st.info("No POC details were found under recognized email headers. Enter a verified contact below; no address is guessed.")
    options = list(range(len(contacts))) + [-1]
    default = next((i for i, c in enumerate(contacts) if c["valid_email"]), 0 if contacts else -1)
    def contact_label(index):
        if index == -1:
            return "Enter contact manually"
        contact = contacts[index]
        return f"POC {contact['poc_group']} · {contact['contact_person']} · {contact['hr_email'] or 'Email missing'}"
    selected = st.selectbox("Recipient / point of contact", options, index=options.index(default),
        format_func=contact_label, key=f"target_contact_{draft['nonce']}", disabled=locked)
    contact = contacts[selected] if selected != -1 else {}
    if contact and not contact["valid_email"]:
        st.info("This POC has no valid email in the directory. Enter a verified recipient before saving.")
    with st.container():
        prefix = f"target_review_{draft['nonce']}_{selected}"
        st.text_input("Target company name", value=by_id[identity]["name"], disabled=True)
        person = st.text_input("Target contact person", value=contact.get("contact_person", "Hiring Team"), key=prefix + "_person", disabled=locked)
        email = st.text_input("Target HR email", value=contact.get("hr_email", ""), key=prefix + "_email", disabled=locked)
        position = st.text_input("Target POC position (optional)", value=contact.get("contact_position", ""), key=prefix + "_position", disabled=locked)
        skills = relevant_skills_picker(root, f"target_skills_{draft['nonce']}", label="Your relevant skills for this company", disabled=locked,
            company_name=by_id[identity]["name"], requirements_prefill=st.session_state.get("partner_requirements_choice_" + identity))
        st.caption("Review the recipient and your own skills. Saving adds a Pending row; drafting and sending remain separate actions.")
        if st.button("Save to Target Companies", type="primary", disabled=locked):
            try:
                current = matcher_store.load().get("directory")
                if not current or current["revision"] != draft["revision"]:
                    raise ValueError("Directory changed. Load this partner's contacts again before saving")
                saved, added = add_partner_target(queue, current, identity,
                    {**contact, "hr_email": email, "contact_person": person, "contact_position": position},
                    relevant_skills=skills)
                st.session_state.preview_company_id = saved.id
                st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1
                st.session_state.pop("confirmation_job", None)
                st.session_state.pop("matcher_target_draft", None)
                st.session_state.matcher_notice = (f"Added {saved.company_name} to Target Companies as Pending."
                    if added else f"{saved.hr_email} is already in Target Companies as {saved.status.title()}; its existing details were preserved.")
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(f"Target company not saved: {exc}")
    if st.button("Cancel target addition", key=f"cancel_target_{draft['nonce']}", disabled=locked):
        st.session_state.pop("matcher_target_draft", None)
        st.rerun()


def _postings(root, store, state, disabled):
    directory = state.get("directory")
    if not directory:
        st.info("Load partner companies in the first tab to discover and match job postings")
        return
    partners = directory["partners"]
    by_id = {p["id"]: p for p in partners}
    location = st.session_state.get("matcher_location", "Philippines")
    search_names = state.get("search_names", {})
    searched = {key for key, value in state["searches"].items() if key in by_id and value["query"] == search_query(by_id[key]["name"], location, search_names.get(key))}
    st.caption(f"Coverage for this location: {len(searched)} / {len(partners)} companies searched. Each search checks up to 10 indexed results; this cannot establish that no vacancies exist.")
    provider = provider_picker(root, "matcher_search_provider", disabled=disabled)
    key = configured_search_key(root)
    ready = provider != "Brave" or bool(key)
    if not ready:
        st.info("Automatic discovery needs BRAVE_SEARCH_API_KEY in your local .env. Partner search links remain available without it. See Discovery setup.")
    selected = st.multiselect("Companies to discover (up to 10)", list(by_id),
                             format_func=lambda k: by_id[k]["name"], max_selections=10, disabled=disabled)
    batch_size = st.number_input("Companies per next batch", min_value=1, max_value=10, value=3, step=1, disabled=disabled)
    st.caption("One provider request per company, no automatic retries. Only company names, C#/.NET keywords, and search location are sent to the selected search provider and its engines; HR addresses, CVs, and email bodies are not sent.")
    run_selected = st.button(f"Discover postings for selected ({len(selected)})", type="primary", disabled=disabled or not selected or not ready)
    remaining = [p["id"] for p in partners if p["id"] not in searched]
    run_next = st.button(f"Discover next {min(int(batch_size), len(remaining))} unsearched companies",
                         disabled=disabled or not ready or not remaining)
    targets = selected if run_selected else remaining[:int(batch_size)] if run_next else []
    if targets:
        progress = st.progress(0, text="Starting discovery…")
        try:
            client = search_client(root, provider, brave_key=key)
        except SearchFailure as exc:
            st.error(str(exc))
            return
        completed = 0
        for i, identity in enumerate(targets):
            partner = by_id[identity]
            query = search_query(partner["name"], location, search_names.get(identity))
            try:
                results = client.search(query)
                leads = leads_from_results(partner, results)
                store.record_search(directory["revision"], identity, query, leads)
                completed += 1
                progress.progress(completed / len(targets), text=f"{partner['name']}: {len(leads)} posting leads")
            except (SearchFailure, ValueError, OSError) as exc:
                st.error(str(exc))
                st.caption(f"Stopped after {completed} completed companies. Completed results are saved; the failing company remains unsearched.")
                break
            if i < len(targets) - 1:
                time.sleep(1.1)
        if completed == len(targets):
            st.session_state.matcher_notice = f"Searched {completed} companies. Posting leads need employer and availability review."
            st.rerun()
        state = store.load()
    leads = list(state["leads"].values())
    st.caption("Saved leads come from search titles/snippets. Company identity and vacancy availability are unverified until you review the posting. A full-time C# vacancy is a hiring signal, not an internship offer.")
    status = st.selectbox("Posting review filter", ["All", "unreviewed", "reviewed", "rejected", "unavailable"])
    filtered = [lead for lead in leads if status == "All" or lead["verification"] == status]
    focus = st.selectbox("Opportunity focus", ["All leads (internships first)", "Internship/OJT leads", "C# mentioned or confirmed", "Reviewed C# internships"])
    def is_intern(lead):
        return lead["role_type"] == "Internship/OJT" if lead["verification"] == "reviewed" else lead["classification"].startswith("Internship")
    if focus == "Internship/OJT leads":
        filtered = [lead for lead in filtered if is_intern(lead)]
    elif focus == "C# mentioned or confirmed":
        filtered = [lead for lead in filtered if lead["language"] == "C# confirmed" or "C# mentioned" in lead["classification"]]
    elif focus == "Reviewed C# internships":
        filtered = [lead for lead in filtered if lead["verification"] == "reviewed" and is_intern(lead) and lead["language"] == "C# confirmed"]
    filtered.sort(key=lambda lead: (not is_intern(lead), lead["partner_name"].casefold()))
    st.dataframe([{"Partner": x["partner_name"], "Role": x["title"], "Evidence classification": x["classification"],
        "Review": x["verification"], "Reviewed role": x["role_type"], "Reviewed language": x["language"],
        "Board": x["board"], "Posting": x["url"], "Checked": x["checked_at"]}
        for x in filtered], hide_index=True, width="stretch",
        column_config={"Posting": st.column_config.LinkColumn("Posting", display_text="Open posting")})
    if not filtered:
        st.caption("No saved postings match this filter. Search links are available in the first tab.")
        return
    lead_id = st.selectbox("Posting to review", [x["id"] for x in filtered],
                          format_func=lambda k: next(f"{x['partner_name']} · {x['title']}" for x in filtered if x["id"] == k))
    lead = state["leads"][lead_id]
    st.link_button("Open original job posting", lead["url"])
    st.text(lead["evidence"])
    st.caption(f"Directory employer: {lead['partner_name']} · Source worksheet: {directory['worksheet']}")
    with st.form(f"lead_review_{lead_id}"):
        employer = st.text_input("Employer name shown on the posting", value=lead["employer"], disabled=disabled)
        role_options, language_options = ["Unknown", "Internship/OJT", "Full-time/other"], ["Unconfirmed", "C# confirmed", ".NET related"]
        role = st.selectbox("Reviewed role type", role_options, index=role_options.index(lead["role_type"]), disabled=disabled)
        language = st.selectbox("Reviewed language evidence", language_options, index=language_options.index(lead["language"]), disabled=disabled)
        outcomes = ["reviewed", "rejected", "unavailable"]
        outcome = st.selectbox("Review outcome", outcomes, index=outcomes.index(lead["verification"]) if lead["verification"] in outcomes else 0, disabled=disabled)
        notes = st.text_area("Matcher review notes", value=lead["notes"], disabled=disabled)
        checked = st.checkbox("I checked the employer identity, role details, and current availability on the source", disabled=disabled)
        if st.form_submit_button("Save posting review", type="primary", disabled=disabled):
            try:
                if not checked:
                    raise ValueError("Check the source-review acknowledgement before saving")
                store.review(lead_id, LeadReview(employer=employer.strip(), role_type=role,
                    language=language, outcome=outcome, notes=notes), lead)
                st.session_state.matcher_notice = "Saved posting review. Application status and applicant skills were preserved."
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(f"Review not saved: {exc}")


def _setup(root):
    st.write("Search links require no API key. Automatic discovery supports Brave, SearXNG, or Hybrid routing. These are search services, not job-board account connections.")
    st.link_button("Open Brave Search API setup", "https://api-dashboard.search.brave.com/")
    st.caption("Check the provider's current plans before creating a key. Configure a key locally; don't paste it into chat or commit it to Git.")
    st.code("BRAVE_SEARCH_API_KEY='your-key-here'", language="dotenv")
    st.caption("Add that variable to the project's .env. This panel reads it again on each rerun; refresh the page after saving. Google Sheets authorization does not grant web-search access.")
    st.code("SEARCH_PROVIDER=Hybrid\nSEARXNG_URL=http://127.0.0.1:8080\nSEARXNG_ENGINES=duckduckgo", language="dotenv")
    st.caption("For local SearXNG setup, follow the README: run scripts/setup_searxng.py, then Docker Compose. Hybrid routes job-board queries to its braveapi engine; no duplicate direct Brave request is made.")
    st.write("Search key: " + ("Configured locally" if configured_search_key(root) else "Not configured"))
    st.caption("Discovery is limited to 10 companies per button click, with no automatic retries or unattended runs. It stores only leads from specific Indeed/JobStreet posting URLs, never search-result pages. Search snippets may be incomplete, stale, or refer to a related company; review them before applying.")
