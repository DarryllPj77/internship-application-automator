"""Read-only sent-message discovery and explicitly reviewed queue reconciliation."""
from core import Company, QueueConflict


async def check_drafted(client, companies, since, progress=lambda *_: None):
    if not companies or len(companies) > 25:
        raise ValueError("Choose 1–25 drafted companies per check")
    if any(c.status != "drafted" or c.needs_review for c in companies):
        raise ValueError("Only Drafted rows without unresolved delivery outcomes can be checked")
    report = []
    async with client.connect() as connection:
        for index, company in enumerate(companies):
            matches = await connection.find_sent(company.hr_email, since)
            report.append({"company": company.model_dump(), "matches": matches})
            progress(index + 1, len(companies))
    return report


def apply_sent_checks(store, report, chosen):
    chosen = set(chosen)
    eligible = {item["company"]["id"]: item for item in report if item["matches"]}
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
            ids = ", ".join(match["message_id"] for match in eligible[company.id]["matches"])
            company = Company.model_validate({**company.model_dump(), "status": "sent",
                "last_result": company.last_result + f"\nManually reviewed Gmail Sent match(es): {ids}"})
        updated.append(company)
    store.replace(updated, current)
    return len(chosen)
