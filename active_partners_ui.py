"""Choose and review the worksheet used by the queue's membership filter."""
import os

from dotenv import dotenv_values
import streamlit as st

from active_partners import build_active_list, load_active_list, save_active_list
from partner_matcher import normalize_company
from sheets_client import SheetsReader
from company_sources import utc_now


def render_active_partner_source(root, companies, *, disabled=False):
    path = root / ".local" / "active-partners.json"
    try:
        snapshot = load_active_list(path)
    except (ValueError, OSError):
        st.error("The saved active-partner list cannot be read. Load and save a reviewed worksheet below to restore the filter.")
        snapshot = None
    with st.expander("Configure active partner list", expanded=snapshot is None):
        st.caption("Choose the worksheet IALAP identifies as the current active FEU Tech partner list. A masterlist or an ‘ongoing’ worksheet is not automatically treated as active. Your personal copy does not refresh from the school original automatically.")
        default_url = snapshot.source_url if snapshot else os.getenv("SHEETS_URL") or dotenv_values(root / ".env").get("SHEETS_URL", "")
        url = st.text_input("Active partner spreadsheet URL", value=default_url, key="active_source_url", disabled=disabled)
        saved_tabs = st.session_state.get("directory_tabs", {})
        own_tabs = st.session_state.get("active_source_tabs", {})
        tabs = own_tabs if own_tabs.get("url") == url else saved_tabs if saved_tabs.get("url") == url else {}
        if st.button("List active-list worksheets", disabled=disabled or not url):
            try:
                tabs = {"url": url, "tabs": SheetsReader().worksheets(url)}
                st.session_state.active_source_tabs = tabs
                st.session_state.pop("active_source_preview", None)
            except Exception as exc:
                st.error(f"Could not list worksheets ({type(exc).__name__}). Check your existing Sheets connection and file access.")
        titles = [tab["title"] for tab in tabs.get("tabs", [])]
        if not titles and snapshot and snapshot.source_url == url:
            titles = [snapshot.worksheet]
        if titles:
            default = titles.index(snapshot.worksheet) if snapshot and snapshot.worksheet in titles else None
            title = st.selectbox("Active partner worksheet", titles, index=default, key="active_source_title", disabled=disabled,
                                 placeholder="Choose the confirmed active FEU Tech worksheet")
            if st.button("Read active worksheet", disabled=disabled or not title):
                try:
                    with st.spinner("Reading the selected worksheet…"):
                        rows = SheetsReader().read(url, title)
                    st.session_state.active_source_preview = {"url": url, "title": title, "rows": rows, "checked_at": utc_now()}
                except Exception as exc:
                    st.error(f"Could not read worksheet ({type(exc).__name__}). The previously saved list was kept.")
            staged = st.session_state.get("active_source_preview", {})
            # Reuse a worksheet already read in Company sources; no second connection needed.
            if staged.get("url") != url or staged.get("title") != title:
                staged = st.session_state.get("directory_matrix", {})
            if staged.get("url") == url and staged.get("title") == title:
                st.caption("Review the first 8 source rows, then set the actual first company row and company-name column.")
                preview = [{"Sheet row": number, **{(chr(65 + i) if i < 26 else "A" + chr(65 + i - 26)): str(value or "")
                    for i, value in enumerate(row[:52])}} for number, row in enumerate(staged["rows"][:8], 1)]
                st.dataframe(preview, hide_index=True, width="stretch")
                first = st.number_input("First active company row", min_value=1, max_value=5000,
                    value=snapshot.first_data_row if snapshot else 4, step=1, key="active_first_row", disabled=disabled)
                column = st.selectbox("Active company-name column", list(range(52)),
                    index=snapshot.company_column if snapshot else 1, key="active_company_column", disabled=disabled,
                    format_func=lambda i: chr(65 + i) if i < 26 else "A" + chr(65 + i - 26))
                candidate = None
                try:
                    candidate = build_active_list(staged["rows"], source_url=url, worksheet=title,
                        first_data_row=int(first), company_column=column)
                    candidate.checked_at = staged.get("checked_at", "unknown (rows reused from Company sources; read again for a fresh timestamp)")
                    st.caption(f"{len(candidate.company_names)} unique company names found with this mapping.")
                except ValueError as exc:
                    st.warning(str(exc))
                confirmed = st.checkbox("I confirmed this worksheet is the current active FEU Tech partner list and checked the company mapping",
                    key="active_source_confirmed_" + str((url, title, first, column)), disabled=disabled)
                if st.button("Use worksheet as active partner list", disabled=disabled or not confirmed or candidate is None):
                    try:
                        save_active_list(path, candidate)
                        snapshot = candidate
                        st.success("Active-partner filter updated. No queue records or application statuses were changed.")
                    except OSError as exc:
                        st.error(f"Could not save the list: {exc}")
        else:
            st.info("Use List active-list worksheets above, or connect and list worksheets in Company sources first.")
    if snapshot:
        names = snapshot.names
        count = sum(any(normalize_company(name) in names for name in
                    [company.company_name, *company.directory_names]) for company in companies)
        st.caption(f"Active-list source: {snapshot.worksheet} · {len(snapshot.company_names)} names · {count} queue matches · Read {snapshot.checked_at}. Matching ignores punctuation and common legal suffixes; subsidiaries are not automatically matched.")
        st.caption("‘Not in active list’ means no name match in this saved worksheet, not proof of an inactive partnership. Refresh the list when the source changes.")
        return names
    st.caption("Active-partner filtering needs a reviewed worksheet. No companies are assumed active from their application status.")
    return None
