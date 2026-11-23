"""Sidebar feature navigation without dropping Streamlit widget state."""
import streamlit as st

SECTIONS = {
    "settings": "01 / Connections & PDF",
    "sources": "02 / Company sources",
    "matcher": "03 / Partner job matcher",
    "import": "04 / Bulk import",
    "add": "05 / Add company",
    "queue": "06 / Company queue",
    "skills": "07 / Queue skills",
    "compose": "08 / Compose & preview",
    "checker": "09 / Check sent drafts",
    "recovery": "10 / Review failed operations",
    "batch": "11 / Batch activity",
}


def navigate(*, disabled=False):
    if destination := st.session_state.pop("next_workspace_section", None):
        st.session_state.workspace_section = destination
    if "workspace_section" not in st.session_state:
        requested = st.query_params.get("view", "")
        legacy = next((key for param, key in (("matcher", "matcher"), ("sources", "sources"), ("skills", "add"))
                       if st.query_params.get(param) == "1"), "settings")
        st.session_state.workspace_section = requested if requested in SECTIONS else legacy
    with st.sidebar:
        st.markdown("### Internship Desk")
        st.caption("APPLICATION WORKSPACE")
        section = st.radio("Workspace section", list(SECTIONS), key="workspace_section",
            format_func=SECTIONS.get, label_visibility="collapsed", disabled=disabled,
            on_change=lambda: st.session_state.pop("confirmation_job", None))
        st.divider()
        st.caption("Start with connections and your PDF. Add or import companies, select skills, review emails, then run your batch. Source and import tools are optional.")
        st.caption("Queue filters and form inputs stay in place when you switch sections.")
    # Keep panels mounted: conditional rendering would delete widget state,
    # including unsaved skill choices and the CV picker, on every section change.
    hidden = []
    if section != "queue":
        hidden.extend((".st-key-queue_metrics", '[data-testid="stLayoutWrapper"]:has(> .st-key-queue_metrics)'))
    for key in SECTIONS:
        if key != section:
            selector = f".st-key-view_{key}"
            hidden.extend((selector, f'[data-testid="stLayoutWrapper"]:has(> {selector})'))
    st.markdown("<style>" + ",".join(hidden) + "{display:none!important}</style>", unsafe_allow_html=True)
    return section
