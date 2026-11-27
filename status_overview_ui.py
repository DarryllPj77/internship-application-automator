"""Read-only company overview available from the shared status counters."""
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
    st.caption(f"{len(matches)} {label.lower()} companies · {descriptions[status]}")
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
    st.dataframe(rows, hide_index=True, width="stretch",
        column_config={"#": st.column_config.NumberColumn("#", format="%d", width="small"),
                       "Description": st.column_config.TextColumn("Description", width="large"),
                       "Failure reason": st.column_config.TextColumn("Failure reason", width="large")})
    st.caption("Viewing this table does not select companies, change statuses, or send emails.")
