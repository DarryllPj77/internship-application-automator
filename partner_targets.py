"""Prepare current directory POCs and append reviewed partners to the mail queue."""
from __future__ import annotations

import re

from core import Company, CompanyStore, EMAIL
from partner_matcher import normalize_company


def selected_partner(directory: dict, partner_id: str) -> dict:
    partner = next((p for p in directory["partners"] if p["id"] == partner_id), None)
    if partner is None:
        raise ValueError("Partner is no longer in this directory; select it again")
    return partner


def partner_contacts(rows: list[list], directory: dict, partner_id: str) -> list[dict]:
    """Re-match names, not stale row numbers; detect POC groups from source headers."""
    partner = selected_partner(directory, partner_id)
    first = directory["first_data_row"]
    column = directory["company_column"]
    headers = rows[:first - 1]
    def key(value):
        return re.sub(r"[^a-z]", "", str(value or "").casefold())
    groups = {}
    industry_column = address_column = None
    for header in headers:
        for index, value in enumerate(header):
            label = key(value)
            if label in ("industry", "typeofindustry"):
                industry_column = index
            if label in ("address", "companyaddress"):
                address_column = index
            if label in ("email", "emailaddress", "emailadd", "emailaddy"):
                preceding = list(range(max(0, index - 4), index))
                names = [i for i in preceding if key(header[i]) in ("name", "contactperson", "contactname", "nameofcontact", "pocname")]
                positions = [i for i in preceding if key(header[i]) in ("position", "title", "jobtitle", "designation")]
                groups[index] = (names[-1] if names else None, positions[-1] if positions else None)
    result, seen = [], set()
    for number, row in enumerate(rows, 1):
        def cell(index):
            return str(row[index] or "").strip() if index is not None and index < len(row) else ""
        if number < first or normalize_company(cell(column)) != normalize_company(partner["name"]):
            continue
        for group_number, (email_column, (name_column, position_column)) in enumerate(sorted(groups.items()), 1):
            person, position, raw = cell(name_column), cell(position_column), cell(email_column)
            if not (person or position or raw):
                continue
            for email in re.split(r"[;,\n]|\s+/\s+", raw):
                email = email.strip()
                identity = (email.casefold(), person.casefold())
                if identity in seen:
                    continue
                seen.add(identity)
                result.append({"contact_person": person or "Hiring Team", "hr_email": email,
                    "contact_position": position, "source_row": number, "poc_group": group_number,
                    "valid_email": bool(EMAIL.fullmatch(email)), "industry": cell(industry_column),
                    "company_address": cell(address_column)})
    return result


def add_partner_target(store: CompanyStore, directory: dict, partner_id: str, contact: dict,
                       *, relevant_skills: str):
    """One reviewed recipient; preserve existing rows and all their mail/recovery state."""
    partner = selected_partner(directory, partner_id)
    company = Company(company_name=partner["name"], hr_email=contact.get("hr_email", ""),
        contact_person=contact.get("contact_person", ""), relevant_skills=relevant_skills,
        contact_position=contact.get("contact_position", ""), source_row=contact.get("source_row"),
        directory_source=directory["source_url"] + " | " + directory["worksheet"],
        industry=contact.get("industry", ""), company_address=contact.get("company_address", ""))
    existing = store.load()
    duplicate = next((c for c in existing if c.hr_email.casefold() == company.hr_email.casefold()), None)
    if duplicate:
        return duplicate, False
    store.replace([*existing, company], existing)
    return company, True
