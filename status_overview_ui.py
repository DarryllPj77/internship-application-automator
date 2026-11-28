"""Company overview with failure filtering and explicitly selected draft preparation."""
import hashlib
import json
import streamlit as st


@st.dialog("Companies by status", width="large")
def show_status_overview(store):
    try:
        companies = store.load()
    except (ValueError, OSError) as exc:
        st.error(f"Could not load the company overview: {exc}")
        return
    label = st.selectbox("Company status", ["Pending", "Drafted", "Sent", "Failed"], key="overview_status")
    status = label.lower()
    descriptions = {
        "pending": "Waiting for a draft or send operation.",
        "drafted": "Recorded as drafted. If sent manually, check Gmail Sent to update the queue.",
        "sent": "Recorded as sent; this does not guarantee inbox delivery.",
        "failed": "Operation or delivery failed. Review the reason before taking action.",
    }
    matches = [company for company in companies if company.status == status]
    total = len(matches)
    if status == "failed" and matches:
        reasons = sorted({c.status_reason.strip() or "No reason recorded" for c in matches})
        options = ["All failure descriptions", *reasons]
        if st.session_state.get("overview_failure_description") not in options:
            st.session_state.overview_failure_description = options[0]
        reason = st.selectbox("Failure description", options, key="overview_failure_description")
        if reason != "All failure descriptions":
            matches = [c for c in matches if (c.status_reason.strip() or "No reason recorded") == reason]
    st.caption(f"{len(matches)} of {total} {label.lower()} companies · {descriptions[status]}")
    if not matches:
        st.info(f"No companies currently have {label} status.")
        return
    rows = []
    for number, company in enumerate(matches, 1):
        description = company.status_reason.strip() or descriptions[status]
        if company.needs_review:
            description += " Check Gmail before retrying: the previous outcome needs review."
        rows.append({"#": number, "Company": company.company_name, "HR email": company.hr_email,
            "Contact person": company.contact_person, "Description": description,
            "Failure reason": (company.status_reason.strip() or "No reason recorded; review failed operations.")
                              if status == "failed" else "—"})
    columns = {"#": st.column_config.NumberColumn("#", format="%d", width="small"),
                       "Description": st.column_config.TextColumn("Description", width="large"),
                       "Failure reason": st.column_config.TextColumn("Failure reason", width="large")}
    if status != "failed":
        st.dataframe(rows, hide_index=True, width="stretch", column_config=columns)
        st.caption("Viewing this table does not change statuses or send emails.")
        return
    locked = store.batch_lock.exists() or "pending_job" in st.session_state
    digest = hashlib.sha256(json.dumps([c.model_dump() for c in matches], sort_keys=True).encode()).hexdigest()[:16]
    base_key, version_key = f"failed_selection_{digest}", f"failed_selection_version_{digest}"
    chosen = st.session_state.get(base_key, [False] * len(matches))
    version = st.session_state.get(version_key, 0)
    select_col, clear_col = st.columns(2)
    select_all = select_col.button("Select all filtered", key="overview_select_failed", disabled=locked)
    clear = clear_col.button("Clear selection", key="overview_clear_failed", disabled=locked)
    if select_all or clear:
        chosen = [bool(select_all and not c.needs_review) for c in matches]
        st.session_state[base_key] = chosen
        version += 1
        st.session_state[version_key] = version
    edited = st.data_editor([{"Select": chosen[i], **row} for i, row in enumerate(rows)],
        key=f"failed_overview_editor_{digest}_{version}", hide_index=True, width="stretch", num_rows="fixed",
        disabled=True if locked else list(rows[0]), column_config=columns)
    selected = [c for c, row in zip(matches, edited) if row["Select"]]
    unresolved = any(c.needs_review for c in selected)
    st.caption(f"{len(selected)} selected. Changing the description filter starts a separate selection; hidden companies are not included.")
    if any(c.needs_review for c in matches):
        st.caption("Select all skips companies with uncertain previous operations. Review those in Review failed operations first.")
    if unresolved:
        st.warning("A selected company has an uncertain previous operation. Review Gmail before preparing another draft.")
    if st.button(f"Prepare drafts for selected ({len(selected)})", type="primary", key="overview_prepare_failed",
                 disabled=locked or not selected or unresolved):
        st.session_state.failed_redraft_request = [c.id for c in selected]
        st.session_state.pop("confirmation_job", None)
        st.session_state.next_workspace_section = "batch"
        st.rerun()
    st.caption("This opens draft review in Batch activity. No status changes or Gmail operations occur until you confirm draft creation.")
