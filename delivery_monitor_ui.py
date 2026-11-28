"""Optional five-minute bounce checks while Internship Desk is open."""
import streamlit as st

from delivery_reports import load_monitor, scan_delivery_reports, update_monitor
from mail_errors import mail_error_message
from mcp_client import GmailMCPClient


@st.fragment(run_every=300)
def render_delivery_monitor(root, store, run_async):
    path = root / ".local" / "delivery-monitor.json"
    try:
        state = load_monitor(path)
    except (OSError, ValueError):
        st.error("Cannot read the delivery monitor state. Restore .local/delivery-monitor.json before scanning.")
        return
    with st.expander("Automatic delivery failure checker", expanded=True):
        st.caption("Routine checks read the 50 newest delivery notices from the last 30 days. Check older notices works backward through Gmail history, up to 50 notices per click. Only notices linked to the newest matching application update the queue. Absence of a bounce never proves inbox delivery.")
        choice = st.selectbox("Delivery monitoring", ["Manual checks", "Automatic every 5 minutes while app is open"],
            index=1 if state.get("enabled") else 0, key="delivery_monitor_mode")
        enabled = choice != "Manual checks"
        try:
            if enabled != bool(state.get("enabled")):
                state = update_monitor(path, enabled=enabled)
            manual = st.button("Check delivery problems now", disabled=store.batch_lock.exists(), key="delivery_scan_now")
            older = st.button("Check older notices", disabled=store.batch_lock.exists() or bool(state.get("older_exhausted")),
                key="delivery_scan_older", help="Continue the saved scan. Confirmed failures and reasons are stored in the company queue; no email is resent.")
            if message := st.session_state.pop("delivery_scan_notice", None):
                st.success(message)
            if manual or older or enabled:
                with st.spinner("Checking Gmail delivery notices…") if manual or older else st.container():
                    result = run_async(scan_delivery_reports(store, GmailMCPClient(), path, force=manual or older, older=older))
                if result.get("skipped"):
                    st.caption(result["skipped"])
                if result.get("updated"):
                    st.session_state.pop("confirmation_job", None)
                    st.session_state.sources_notice = f"Updated {result['updated']} delivery outcomes. No emails were resent."
                    st.session_state.delivery_scan_notice = f"Saved {result['updated']} delivery outcomes with reasons. No emails were resent."
                    st.rerun()
                if manual or older:
                    st.success(f"Check complete. {result.get('inspected', 0)} new notices inspected; no new status changes.")
                if result.get("truncated"):
                    st.warning("The newest 50-notice limit was reached. Use Check older notices to continue through earlier delivery notices.")
                state = load_monitor(path)
            if state.get("older_exhausted"):
                st.caption("Older-notice scan reached the end of its search. Any unrecognized or unconfirmed notices still need manual review.")
            elif state.get("older_pending") or state.get("older_before"):
                st.caption("Older-notice progress saved. Click Check older notices again to continue, even after refreshing the app.")
            if state.get("older_retry_ids"):
                st.warning(f"{len(state['older_retry_ids'])} older notices could not yet be confirmed against the latest application. No failure was assumed for them; review Gmail manually.")
            if state.get("last_checked_at"):
                st.caption("Last delivery check: " + state["last_checked_at"])
            events = sorted(state.get("events", []), key=lambda item: item["notice_at"], reverse=True)
            if events:
                st.dataframe([{"Company": item["company_name"], "To": item["recipient"],
                    "Outcome": "Failed" if item["kind"] == "failed" else "Delivery delayed", "Short reason": item["reason"],
                    "Notice date": item["notice_at"], "Gmail notice": "https://mail.google.com/mail/u/0/#all/" + item["notice_id"]}
                    for item in events], hide_index=True, width="stretch",
                    column_config={"Gmail notice": st.column_config.LinkColumn("Gmail notice", display_text="Review notice")})
            st.caption("Automatic checks pause during a batch and stop when the app/browser session closes. This checker never resends an email. Delays remain separate from final failures; Gmail may already be retrying them.")
        except Exception as exc:
            st.error("Delivery check stopped: " + mail_error_message(exc))
