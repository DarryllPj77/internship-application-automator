"""Gmail read-only checks and local confirmed-failure/status reconciliation; never sends mail."""
from core import Company, QueueConflict


async def check_with_delivery(store, client, companies, since, state_path, progress=lambda *_: None):
    """Inspect Sent and persist only independently confirmed delivery failures."""
    from delivery_reports import scan_delivery_reports
    report = await check_drafted(client, companies, since, progress)
    outcome = await scan_delivery_reports(store, client, state_path, force=True,
        company_ids=[company.id for company in companies],
        sent_matches={item["company"]["id"]: item["matches"] for item in report})
    current = {company.id: company.model_dump() for company in store.load()}
    for item in report:
        item["company"] = current.get(item["company"]["id"], item["company"])
    return report, outcome


async def check_drafted(client, companies, since, progress=lambda *_: None):
    if not companies or len(companies) > 25:
        raise ValueError("Choose 1–25 drafted companies per check")
    if any(c.status not in ("drafted", "sent", "failed") or c.needs_review for c in companies):
        raise ValueError("Only Drafted, Sent, or Failed rows without unresolved delivery outcomes can be checked")
    report = []
    async with client.connect() as connection:
        for index, company in enumerate(companies):
            matches = await connection.find_sent(company.hr_email, since)
            report.append({"company": company.model_dump(), "matches": matches})
            progress(index + 1, len(companies))
    return report


def apply_sent_checks(store, report, chosen, *, outcome="sent", reason=""):
    if outcome not in ("sent", "failed", "delayed"):
        raise ValueError("Choose Sent, Failed, or Delivery delayed")
    if outcome != "sent" and not reason.strip():
        raise ValueError("Add a short delivery reason before saving")
    chosen = set(chosen)
    eligible = {item["company"]["id"]: item for item in report if item["matches"] or outcome != "sent"}
    if not chosen or not chosen <= eligible.keys():
        raise ValueError("Select reviewed rows with matching sent messages")
    current = store.load()
    by_id = {company.id: company for company in current}
    for identity in chosen:
        if identity not in by_id or by_id[identity].model_dump() != eligible[identity]["company"]:
            raise QueueConflict("A checked company changed. Run the sent checker again before updating statuses")
    updated = []
    for company in current:
        if company.id in chosen:
            if outcome == "sent" and company.delivery_state == "failed":
                raise ValueError("This application has a recorded delivery failure. Verify a new send before marking it Sent")
            ids = ", ".join(match["message_id"] for match in eligible[company.id]["matches"])
            note = f"\nManually reviewed Gmail Sent match(es): {ids}" if outcome == "sent" else f"\nManually reviewed delivery outcome: {outcome}. {reason.strip()}"
            company = Company.model_validate({**company.model_dump(), "status": "failed" if outcome == "failed" else "sent",
                "status_reason": reason.strip() if outcome != "sent" else company.status_reason,
                "delivery_state": outcome if outcome in ("failed", "delayed") else company.delivery_state,
                "needs_review": False, "last_result": company.last_result + note})
        updated.append(company)
    store.replace(updated, current)
    return len(chosen)
