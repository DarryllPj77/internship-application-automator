"""Company requirement discovery and explicit source review, shared by entry points."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st

from company_sources import utc_now
from partner_matcher import BraveSearch, configured_search_key
from search_providers import provider_picker, search_client
from requirements_search import (SOURCES, RequirementsStore, requirements_query, search_candidates,
                                 read_requirements, extract_required_section)

QUALITY = {"search_excerpt": "Search excerpt only — incomplete",
           "posting_section": "Requirements section from a public posting",
           "structured_qualifications": "Structured job qualifications from a public posting",
           "user_pasted_text": "Posting text supplied by you"}


def evidence_label(kind):
    prefix = "Edited by you · " if kind.startswith("user_edited_") else ""
    return prefix + QUALITY.get(kind.removeprefix("user_edited_"), "Reviewed source text")


def requirements_finder(root: Path, key: str, company_name: str, *, search_name="", disabled=False):
    """Return an evidence record only when the user explicitly applies a reviewed source."""
    if not company_name.strip():
        return None
    scope = key + "_" + hashlib.sha256(company_name.encode()).hexdigest()[:12]
    store = RequirementsStore(root / ".local" / "company-requirements.json")
    with st.expander("Find company job requirements", expanded=st.query_params.get("requirements") == "1"):
        st.caption(f"Company: {company_name}. Search a specific role, then review the employer and source before using its requirements.")
        role = st.text_input("Role / job keywords", value="software developer intern", key=scope + "_role", max_chars=120, disabled=disabled)
        location = st.text_input("Requirements search location", value="Philippines", key=scope + "_location", max_chars=100, disabled=disabled)
        sources = st.multiselect("Requirements search sources", SOURCES, default=SOURCES, key=scope + "_sources", disabled=disabled)
        provider = provider_picker(root, scope + "_provider", disabled=disabled)
        api_key = configured_search_key(root)
        if provider == "Brave" and not api_key:
            st.info("Live search needs BRAVE_SEARCH_API_KEY in the local .env. Existing results and manual requirements remain usable.")
            st.link_button("Search API setup", "https://api-dashboard.search.brave.com/documentation/guides/authentication")
        st.caption("One provider request per click, up to 10 results. Only company, role, location, and source filters are sent; resume text and HR details stay local.")
        try:
            state = store.load()
        except (OSError, ValueError):
            st.error("Cannot read .local/company-requirements.json. Restore that file before searching.")
            return None
        query = requirements_query(company_name, role, location, sources, search_name) if sources else ""
        context = hashlib.sha256(json.dumps([company_name, query, provider], ensure_ascii=False).encode()).hexdigest()
        if st.button("Search company job requirements", key=scope + "_search", disabled=disabled or (provider == "Brave" and not api_key) or not sources):
            try:
                with st.spinner("Searching indexed job postings…"):
                    found = search_candidates(company_name, search_client(root, provider, brave_key=api_key).search(query), sources)
                record = {"company_name": company_name, "query": query, "provider": provider, "checked_at": utc_now(), "candidates": found}
                store.save("searches", context, record)
                state["searches"][context] = record
            except (ValueError, OSError) as exc:
                st.error(f"Requirements search stopped: {exc}")
        legacy_context = hashlib.sha256(json.dumps([company_name, query], ensure_ascii=False).encode()).hexdigest()
        saved = state["searches"].get(context) or state["searches"].get(legacy_context)
        if not saved:
            return None
        candidates = saved["candidates"]
        st.caption(f"Search checked {saved['checked_at']}. Indexed results can be stale or belong to another employer; no result does not prove there are no vacancies.")
        if not candidates:
            st.info("No specific posting candidates found. Try a broader role, another source selection, or paste a known posting into the requirements field.")
            return None
        by_id = {item["id"]: item for item in candidates}
        st.dataframe([{"Role / page title": x["title"], "Source": x["source"], "Posting": x["url"]} for x in candidates],
            hide_index=True, width="stretch", column_config={"Posting": st.column_config.LinkColumn("Posting", display_text="Open posting")})
        selected = st.selectbox("Posting to inspect for requirements", list(by_id),
            format_func=lambda value: by_id[value]["title"] + " · " + by_id[value]["source"], key=scope + "_posting_" + context[:10], disabled=disabled)
        candidate = by_id[selected]
        st.link_button("Open requirements source", candidate["url"])
        st.text(candidate["excerpt"] or "No search excerpt supplied")
        document = state["documents"].get(candidate["url"])
        if candidate["source"] == "Company career pages":
            if st.button("Read full posting requirements", key=scope + "_read_" + selected, disabled=disabled):
                try:
                    with st.spinner("Reading the public posting…"):
                        document = read_requirements(candidate)
                    store.save("documents", candidate["url"], document)
                except Exception as exc:
                    st.warning(f"Full requirements could not be read ({type(exc).__name__}). Review the excerpt or paste the posting text below.")
        else:
            st.caption("This board is represented by its indexed excerpt. Full account-page scraping and access-control bypasses are not used. Open the posting and paste its required qualifications when the excerpt is incomplete.")
        pasted = st.text_area("Full posting text (optional)", key=scope + "_paste_" + selected,
                               max_chars=20000, height=110, disabled=disabled)
        if st.button("Extract requirements from pasted text", key=scope + "_extract_" + selected, disabled=disabled or not pasted.strip()):
            document = {"url": candidate["url"], "title": candidate["title"], "employer": "",
                "text": extract_required_section(pasted) or pasted, "evidence_type": "user_pasted_text", "checked_at": utc_now()}
            try:
                store.save("documents", candidate["url"], document)
            except (ValueError, OSError) as exc:
                st.error(f"Posting text not saved: {exc}")
                return None
        evidence_type = document["evidence_type"] if document else "search_excerpt"
        original_text = document["text"] if document else extract_required_section(candidate["excerpt"]) or candidate["excerpt"]
        st.markdown("**Evidence: " + evidence_label(evidence_type) + "**")
        if document:
            st.caption(f"Employer shown: {document.get('employer') or 'Unknown'} · Posted: {document.get('posting_date') or 'Unknown'} · Expires: {document.get('expires') or 'Unknown'} · Read: {document['checked_at']}")
        version = hashlib.sha256((evidence_type + original_text).encode()).hexdigest()[:10]
        review_key = scope + "_review_" + selected + version
        reviewed_text = st.text_area("Review requirements to use", value=original_text, key=review_key,
                                     max_chars=20000, height=180, disabled=disabled)
        confirmed = st.checkbox("I confirmed this posting belongs to the selected company and reviewed the required qualifications and availability",
                                key=review_key + "_confirmed", disabled=disabled)
        if st.button("Use reviewed requirements", key=review_key + "_apply", type="primary",
                     disabled=disabled or not confirmed or not reviewed_text.strip()):
            try:
                quality = evidence_type if reviewed_text == original_text else "user_edited_" + evidence_type
                applied_candidate = {**candidate, "checked_at": document["checked_at"] if document else candidate["checked_at"],
                    "title": document.get("title", candidate["title"]) if document else candidate["title"],
                    "content_url": document.get("url") if document else candidate["url"]}
                return store.apply(company_name, applied_candidate, reviewed_text, quality, employer_confirmed=confirmed)
            except (ValueError, OSError) as exc:
                st.error(f"Requirements not applied: {exc}")
    return None
