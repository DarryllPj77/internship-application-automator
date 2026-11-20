"""Shared resume skill selection with explicit requirements matching and editable wording."""
from pathlib import Path
import os

import streamlit as st
from dotenv import dotenv_values

from resume_skills import pdf_skills, match_required_skills
from requirements_ui import requirements_finder, evidence_label
from partner_matcher import normalize_company


@st.cache_data(show_spinner=False, max_entries=12)
def _read_skills(path: str, modified: int, size: int):
    return pdf_skills(Path(path).read_bytes())


def _selection_changed(key):
    st.session_state[key + "_text"] = ", ".join(st.session_state.get(key + "_selected", []))


def _resume_changed(key):
    st.session_state[key + "_selected"] = []
    st.session_state[key + "_text"] = ""


def _match(key, available):
    selected = match_required_skills(list(available), st.session_state.get(key + "_requirements", ""))
    st.session_state[key + "_selected"] = selected
    st.session_state[key + "_text"] = ", ".join(selected)
    st.session_state[key + "_matched"] = True


def relevant_skills_picker(root: Path, key: str, *, label="Relevant skills", disabled=False, company_name="", requirements_prefill=None):
    candidates = []
    selected_cv = st.session_state.get("cv_path") or dotenv_values(root / ".env").get("CV_FILE_PATH") or os.getenv("CV_FILE_PATH", "")
    if selected_cv:
        path = Path(os.path.expandvars(selected_cv)).expanduser()
        if path.is_file() and path.suffix.casefold() == ".pdf":
            candidates.append(str(path.resolve()))
    uploads = list((root / "uploads" / "cvs").glob("*/*.pdf"))
    for path in sorted(uploads, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        if str(path.resolve()) not in candidates:
            candidates.append(str(path.resolve()))
    available = []
    if candidates:
        source = st.selectbox("CV for skill suggestions", candidates, format_func=lambda p: Path(p).name,
            key=key + "_resume", on_change=_resume_changed, args=(key,), disabled=disabled)
        try:
            metadata = Path(source).stat()
            if metadata.st_size > 20 * 1024 * 1024:
                raise ValueError("Choose a PDF CV up to 20 MB")
            available = _read_skills(source, metadata.st_mtime_ns, metadata.st_size)
            fingerprint = (source, metadata.st_mtime_ns, metadata.st_size)
            previous = st.session_state.get(key + "_fingerprint")
            if previous and previous != fingerprint:
                _resume_changed(key)
            st.session_state[key + "_fingerprint"] = fingerprint
            st.caption(f"Detected {len(available)} known skill names from {Path(source).name}. Review suggestions; extraction may miss skills. This selection does not change the email attachment.")
        except (ValueError, OSError) as exc:
            st.warning(str(exc))
    else:
        st.caption("Upload or select your PDF CV above to populate this dropdown. You can also type relevant skills below.")
    chosen = st.session_state.get(key + "_selected", [])
    if any(skill not in available for skill in chosen):
        st.session_state[key + "_selected"] = [skill for skill in chosen if skill in available]
    context = normalize_company(company_name)
    previous_context = st.session_state.get(key + "_company_context")
    if previous_context and previous_context != context and st.session_state.get(key + "_requirements_origin"):
        for suffix in ("_requirements", "_text"):
            st.session_state[key + suffix] = ""
        st.session_state[key + "_selected"] = []
        st.session_state.pop(key + "_requirements_origin", None)
    st.session_state[key + "_company_context"] = context
    reviewed = requirements_finder(root, key + "_finder", company_name, disabled=disabled)
    reviewed = reviewed or requirements_prefill
    if reviewed and normalize_company(reviewed["company_name"]) == context and st.session_state.get(key + "_requirements_origin") != reviewed["review_id"]:
        st.session_state[key + "_requirements"] = reviewed["text"]
        st.session_state[key + "_requirements_origin"] = reviewed["review_id"]
        st.session_state[key + "_requirements_evidence"] = reviewed
        if available:
            _match(key, available)
    origin = st.session_state.get(key + "_requirements_evidence")
    if origin and st.session_state.get(key + "_requirements_origin"):
        st.link_button("Applied requirements source", origin["url"])
        st.text("Reviewed role: " + origin["title"])
        st.caption(f"{evidence_label(origin['evidence_type'])} · Reviewed {origin['reviewed_at']}. Final requirements and skills remain editable.")
    st.text_area("Required skills / job requirements", key=key + "_requirements", height=100, disabled=disabled,
                 help="Paste the required-skills section of the posting. Company names alone cannot identify requirements.")
    st.button("Select matching resume skills", key=key + "_match", disabled=disabled or not available,
              on_click=_match, args=(key, tuple(available)))
    if st.session_state.pop(key + "_matched", False):
        if st.session_state.get(key + "_selected"):
            st.caption("Selected only resume skills mentioned in your supplied requirements. Check the selection before saving.")
        else:
            st.info("No matching required resume skills found. Choose the relevant ones manually or edit the final text.")
    st.multiselect("Resume skills (choose only relevant ones)", available, key=key + "_selected",
        on_change=_selection_changed, args=(key,), disabled=disabled or not available)
    st.caption("Starts empty; all resume skills are never added automatically. Changing the selection updates the editable text below. Manual edits remain until you change the selection or run matching again.")
    return st.text_input(label, key=key + "_text", disabled=disabled)
