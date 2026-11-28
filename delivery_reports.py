"""Conservative Gmail delivery-notice matching. Never retries or sends mail."""
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime

from core import Company, EMAIL, SUBJECT, QueueConflict, atomic_text, exclusive_lock


def utcnow():
    return datetime.now(timezone.utc)


def mail_date(value):
    try:
        result = parsedate_to_datetime(value)
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def split_message(text):
    head, _, body = text.replace("\r", "").partition("\n\n")
    return dict(line.split(": ", 1) for line in head.splitlines() if ": " in line), body


def parse_notice(identity, text):
    headers, body = split_message(text)
    senders = getaddresses([headers.get("From", "")])
    if len(senders) != 1 or not re.fullmatch(r"(?:mailer-daemon|postmaster)(?:[+\w.-]*)", senders[0][1].split("@")[0], re.I):
        return None
    # Ignore quoted original-message content when deciding the delivery outcome.
    diagnostic = re.split(r"Original Message (?:Details|Headers)|Attachments \(\d+\):", body, maxsplit=1, flags=re.I)[0]
    limit_notice = (senders[0][1].casefold() in ("mailer-daemon@googlemail.com", "mailer-daemon@gmail.com")
        and re.sub(r"^(?:re:\s*)+", "", headers.get("Subject", ""), flags=re.I) == SUBJECT
        and re.sub(r"\s+", " ", diagnostic).strip().casefold().startswith(
            "you have reached a limit for sending mail. your message was not sent."))
    if not limit_notice and not re.search(r"delivery status notification|undeliverable|mail delivery|delivery fail", headers.get("Subject", ""), re.I):
        return None
    recipients = re.findall(r"^Final-Recipient:\s*rfc822;\s*(" + EMAIL.pattern + r")", diagnostic, re.I | re.M)
    if not recipients:
        recipients = re.findall(r"(?:your message (?:wasn't delivered to|couldn't be delivered to|to)|delivering your message to)\s+(" + EMAIL.pattern + r")", diagnostic, re.I)
    recipients = {address.casefold() for address in recipients}
    if not limit_notice and len(recipients) != 1:
        return None
    action = re.findall(r"^Action:\s*(\w+)", diagnostic, re.I | re.M)
    action = {value.lower() for value in action}
    if len(action) > 1:
        return None
    lower = diagnostic.casefold()
    delayed = action == {"delayed"} or (not action and ("(delay)" in headers.get("Subject", "").lower() or "gmail will retry" in lower))
    failed = action == {"failed"} or (not action and ("(failure)" in headers.get("Subject", "").lower() or headers.get("Subject", "").lower().startswith("undeliverable:")))
    if limit_notice:
        kind, reason = "failed", "Gmail sending limit reached; message was not sent. Review before retrying."
    elif delayed:
        kind, reason = "delayed", "Delivery delayed; Gmail reported a temporary problem. No final failure confirmed."
    elif failed:
        kind = "failed"
        if re.search(r"inbox (?:is )?full|mailbox (?:is )?full", lower):
            reason = "Recipient inbox is full."
        elif "address not found" in lower or "does not exist" in lower or "5.1.1" in lower:
            reason = "Recipient email address was not found."
        elif re.search(r"timed? out|requests to connect|could not connect|connection refused", lower):
            reason = "Recipient mail server could not be reached; delivery failed."
        elif re.search(r"blocked|access denied|mail flow rule|organization policy|rejected", lower):
            reason = "Recipient server blocked or rejected the message."
        else:
            reason = "Gmail reported final delivery failure. Review the delivery notice."
    else:
        return None
    date = mail_date(headers.get("Date", ""))
    if not date or not headers.get("Thread ID"):
        return None
    return {"notice_id": identity, "thread_id": headers["Thread ID"], "recipient": None if limit_notice else next(iter(recipients)),
            "kind": kind, "reason": reason, "notice_at": date.isoformat()}


def load_monitor(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"enabled": False, "seen": [], "events": []}


def update_monitor(path, **changes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path.with_suffix(".write.lock")):
        state = load_monitor(path)
        state.update(changes)
        atomic_text(path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return state


async def scan_delivery_reports(store, client, state_path, *, force=False, older=False, company_ids=None, sent_matches=None):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(state_path.with_suffix(".scan.lock")):
        if store.batch_lock.exists():
            return {"updated": 0, "skipped": "A batch is running; delivery checking will wait."}
        state = load_monitor(state_path)
        last = datetime.fromisoformat(state["last_checked_at"]) if state.get("last_checked_at") else None
        if company_ids is None and not older and not force and last and (utcnow() - last).total_seconds() < 300:
            return {"updated": 0}
        if older and state.get("older_exhausted"):
            return {"updated": 0, "inspected": 0, "older_complete": True}
        companies = store.load()
        scope = set(company_ids) if company_ids is not None else None
        by_email = {}
        for company in companies:
            if scope is not None and company.id not in scope:
                continue
            if company.status != "pending" and (company.status in ("sent", "drafted") or company.delivery_state in ("failed", "delayed")):
                by_email.setdefault(company.hr_email.casefold(), []).append(company)
        if not by_email:
            return {"updated": 0, "skipped": "No submitted or drafted applications to check."}
        seen = list(state.get("seen", []))
        known = set(seen) if scope is None else set()  # Explicit checks revisit notices skipped by older parsers.
        retry_ids = set()
        events, sent_cache = {}, dict(sent_matches or {})
        thread_hints = {**state.get("sent_thread_hints", {}), **(sent_matches or {})}
        inspected = 0
        older_changes = {}
        async with client.connect() as connection:
            ids = []
            truncated = False
            if older:
                pending = [identity for identity in state.get("older_pending", []) if identity not in known]
                exhausted = bool(state.get("older_last_page", False))
                if not pending:
                    before = int(state.get("older_before", int(utcnow().timestamp()) + 1))
                    metadata = await connection.read_tool("search_emails", {
                        "query": f"{{from:mailer-daemon from:postmaster}} before:{before}", "maxResults": 500})
                    batch_ids = list(dict.fromkeys(re.findall(r"^ID: ([a-fA-F0-9]+)\s*$", metadata, re.M)))
                    if metadata.strip() and not batch_ids:
                        raise ValueError("Unrecognized older-notice search output; progress was not advanced")
                    exhausted = len(batch_ids) < 500
                    if not exhausted:
                        dates = [mail_date(value) for value in re.findall(r"^Date: (.+)$", metadata, re.M)]
                        if len(dates) != len(batch_ids) or any(value is None for value in dates):
                            raise ValueError("Cannot safely date-page older notices; progress was not advanced")
                        # Overlap the oldest second so equal-time messages are never silently skipped.
                        boundary = int(min(dates).timestamp()) + 1
                        if boundary >= before:
                            raise ValueError("Too many notices share the oldest time boundary. Manual review is needed; progress was not advanced")
                        older_changes["older_before"] = boundary
                    pending = [identity for identity in batch_ids if identity not in known]
                ids, remainder = pending[:50], pending[50:]
                older_changes.update(older_pending=remainder, older_last_page=exhausted,
                                     older_exhausted=exhausted and not remainder)
            else:
                metadata = await connection.read_tool("search_emails", {
                    "query": "{from:mailer-daemon from:postmaster} newer_than:30d", "maxResults": 50})
                ids = list(dict.fromkeys(re.findall(r"^ID: ([a-fA-F0-9]+)\s*$", metadata, re.M)))
                if metadata.strip() and not ids:
                    raise ValueError("Unrecognized delivery-notice search output; no statuses changed")
                truncated = len(ids) >= 50
            for identity in ids:
                if identity in known:
                    continue
                text = await connection.read_tool("read_email", {"messageId": identity})
                notice = parse_notice(identity, text)
                inspected += 1
                seen.append(identity)
                if not notice:
                    continue
                if notice["recipient"] is None:
                    matches = [company for group in by_email.values() for company in group
                               if any(message.get("thread_id") == notice["thread_id"]
                                      for message in thread_hints.get(company.id, []))]
                else:
                    matches = by_email.get(notice["recipient"], [])
                if len(matches) != 1:
                    if scope is not None or notice["recipient"] is None:
                        retry_ids.add(identity)
                    continue
                company = matches[0]
                if company.id not in sent_cache:
                    sent_cache[company.id] = await connection.find_sent(company.hr_email,
                        datetime(1970, 1, 1).date() if older else (utcnow() - timedelta(days=30)).date())
                sent = [message for message in sent_cache[company.id] if mail_date(message.get("date", ""))]
                if not sent:
                    retry_ids.add(identity)
                    continue
                latest = max(sent, key=lambda message: mail_date(message["date"]))
                sent_at = mail_date(latest["date"])
                # A DSN must belong to the newest application, not an older attempt.
                if latest.get("thread_id") != notice["thread_id"]:
                    retry_ids.add(identity)
                    continue
                if sent_at > datetime.fromisoformat(notice["notice_at"]):
                    continue
                if company.last_operation_at and sent_at < datetime.fromisoformat(company.last_operation_at) - timedelta(seconds=2):
                    continue
                if company.delivery_outbound_id == latest["message_id"]:
                    if company.delivery_state == "failed" and notice["kind"] != "failed":
                        continue
                    if company.delivery_notice_at and notice["notice_at"] <= company.delivery_notice_at:
                        continue
                event = {**notice, "recipient": company.hr_email, "company_id": company.id, "company_name": company.company_name,
                         "outbound_id": latest["message_id"]}
                previous = events.get(company.id)
                if previous and (previous["kind"] == "failed" and event["kind"] != "failed" or previous["kind"] == event["kind"] and previous["notice_at"] >= event["notice_at"]):
                    continue
                events[company.id] = event
        current = store.load()
        originals = {company.id: company for company in companies}
        updated, applied = [], []
        for company in current:
            event = events.get(company.id)
            if event and company == originals[company.id] and not company.needs_review:
                company = Company.model_validate({**company.model_dump(),
                    "status": "failed" if event["kind"] == "failed" else "sent", "status_reason": event["reason"],
                    "delivery_state": event["kind"], "delivery_notice_id": event["notice_id"],
                    "delivery_notice_at": event["notice_at"], "delivery_outbound_id": event["outbound_id"]})
                applied.append(event)
            elif event:
                retry_ids.add(event["notice_id"])
            updated.append(company)
        if applied:
            store.replace(updated, current)
        history = {event["notice_id"]: event for event in state.get("events", [])}
        history.update({event["notice_id"]: event for event in applied})
        if older and retry_ids:
            older_changes["older_retry_ids"] = list(dict.fromkeys([*state.get("older_retry_ids", []), *retry_ids]))
        update_monitor(state_path, seen=list(dict.fromkeys(identity for identity in seen if identity not in retry_ids))[-2000:],
                       events=list(history.values())[-100:], last_checked_at=utcnow().isoformat(),
                       sent_thread_hints=thread_hints, **older_changes)
        return {"updated": len(applied), "inspected": inspected, "events": applied, "truncated": truncated,
                "older_complete": older and older_changes.get("older_exhausted", False),
                "older_unresolved": len(older_changes.get("older_retry_ids", state.get("older_retry_ids", [])))}
