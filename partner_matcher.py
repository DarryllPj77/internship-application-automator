"""FEU directory snapshots, job-board search links and reviewable search-result leads."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs, urlunsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

from company_sources import utc_now
from core import atomic_text, exclusive_lock, QueueConflict, clean_company_name

LEGAL_SUFFIX = re.compile(r"\s+(?:incorporated|inc|corporation|corp|limited|ltd|llc|plc|opc|company|co)$")
CSHARP = re.compile(r"(?<!\w)c\s*#|\bc[ -]?sharp\b", re.I)
DOTNET = re.compile(r"(?<!\w)\.net\b|\basp\.?net\b|\bvb\.net\b|\bdotnet\b", re.I)
INTERN = re.compile(r"\bintern(?:ship)?\b|\bojt\b|on.the.job training", re.I)
ROLE = re.compile(r"\bdeveloper\b|\bengineer\b|\bprogrammer\b|\bintern(?:ship)?\b|\bojt\b", re.I)


def normalize_company(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value.replace("&", " and ")).strip()
    while LEGAL_SUFFIX.search(value):
        value = LEGAL_SUFFIX.sub("", value)
    return value


def employer_matches(partner: str, employer: str) -> bool:
    # Related subsidiaries are deliberately NOT treated as the same legal employer.
    return bool(normalize_company(partner)) and normalize_company(partner) == normalize_company(employer)


def partner_snapshot(rows, *, source_url: str, worksheet: str, first_data_row=4, company_column=1):
    if not 1 <= first_data_row <= 5000 or not 0 <= company_column < 52:
        raise ValueError("Choose a valid first row and company column")
    partners = {}
    for number, row in enumerate(rows, 1):
        if number < first_data_row or company_column >= len(row):
            continue
        name = clean_company_name(str(row[company_column] or ""))
        normalized = normalize_company(name)
        if not normalized:
            continue
        identity = hashlib.sha256(normalized.encode()).hexdigest()[:24]
        if identity in partners:
            partners[identity]["source_rows"].append(number)
        else:
            partners[identity] = {"id": identity, "name": name, "source_rows": [number]}
    if not partners:
        raise ValueError("No company names found; check the worksheet and column mapping")
    if len(partners) > 5000:
        raise ValueError("Use at most 5,000 companies per directory")
    result = {"source_url": source_url, "worksheet": worksheet, "first_data_row": first_data_row,
              "company_column": company_column, "partners": list(partners.values())}
    result["revision"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    result["checked_at"] = utc_now()
    return result


def suggested_search_name(name: str) -> str:
    """Shorten search terms only; never change the directory identity or match rules."""
    value = re.sub(r'[*†‡]+', '', name).replace('"', '').strip()
    value = re.sub(r"\s*[-–—,]?\s*\b(?:ROHQ|regional operating headquarters)\b\.?\s*$", "", value, flags=re.I).strip()
    value = re.sub(r"(?:[\s,.]+(?:pty|ltd|limited|inc|incorporated|corp|corporation|llc|plc|opc|co|company)\.?)+(?:\s+philippines)?\s*$", "", value, flags=re.I).strip(" ,.-")
    return re.sub(r"\s+", " ", value) or name.strip()


def search_links(name: str, location="Philippines", *, search_name=None) -> dict:
    query_name = search_name.strip() if search_name else suggested_search_name(name)
    return {
        "Indeed search": "https://ph.indeed.com/jobs?" + urlencode({"q": query_name, "l": location}),
        "JobStreet search": "https://ph.jobstreet.com/jobs?" + urlencode({"keywords": query_name, "where": location})}


def export_searches(partners, location="Philippines", search_names=None) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["company", "source_rows", "search_name", "Indeed search", "JobStreet search"])
    for partner in partners:
        # Guard spreadsheet formula execution in exported company cells.
        name = partner["name"]
        safe_name = "'" + name if name.lstrip().startswith(("=", "+", "-", "@")) else name
        query_name = (search_names or {}).get(partner.get("id"), suggested_search_name(name))
        safe_query = "'" + query_name if query_name.lstrip().startswith(("=", "+", "-", "@")) else query_name
        writer.writerow([safe_name, ", ".join(map(str, partner["source_rows"])), safe_query,
            *search_links(name, location, search_name=query_name).values()])
    return output.getvalue().encode("utf-8-sig")


def canonical_posting(url: str) -> tuple[str, str] | None:
    """Only specific job pages qualify; search pages never become discovered postings."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return None
    if host in ("ph.indeed.com", "www.indeed.com", "indeed.com"):
        job_id = parse_qs(parsed.query).get("jk", [""])[0]
        if parsed.path in ("/viewjob", "/m/viewjob", "/rc/clk") and re.fullmatch(r"[A-Za-z0-9_-]{5,80}", job_id):
            return "https://" + host + "/viewjob?" + urlencode({"jk": job_id}), "Indeed"
    if host == "ph.jobstreet.com":
        match = re.fullmatch(r"/job/(\d+)(?:/[^/]*)?/?", parsed.path)
        if match:
            return urlunsplit(("https", host, "/job/" + match[1], "", "")), "JobStreet"
    return None


def classify(title: str, evidence: str) -> str:
    text = title + " " + evidence
    language = "C# mentioned" if CSHARP.search(text) else ".NET related; C# unconfirmed" if DOTNET.search(text) else "No technology evidence"
    # Job type is derived from TITLE only; a snippet mentioning an internship programme
    # must not turn a senior developer job into an internship.
    role_type = "Internship/OJT lead" if INTERN.search(title) else "Developer hiring lead" if ROLE.search(title) else "Role type unclear"
    return role_type + " · " + language


def search_query(name: str, location: str, search_name=None) -> str:
    safe = re.sub(r'["\r\n]', " ", search_name or suggested_search_name(name))[:200]
    return f'"{safe}" ("C#" OR "Csharp" OR ".NET" OR "ASP.NET") (site:ph.indeed.com OR site:ph.jobstreet.com) {location[:100]}'


class SearchFailure(ValueError):
    pass


class BraveSearch:
    def __init__(self, key: str):
        if not key.strip():
            raise SearchFailure("Set BRAVE_SEARCH_API_KEY in your local .env first")
        self.key = key

    def search(self, query: str):
        import requests
        try:
            response = requests.get("https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 10, "country": "ph", "search_lang": "en", "extra_snippets": "true"},
                headers={"X-Subscription-Token": self.key, "Accept": "application/json"}, timeout=(5, 15), allow_redirects=False)
        except requests.RequestException:
            raise SearchFailure("Search network request failed; no automatic retry was made") from None
        if response.status_code != 200:
            message = {401: "Search key was rejected", 403: "Search access was denied; check your provider plan",
                       429: "Search rate limit reached; stop and try a later batch"}.get(response.status_code, "Search provider request failed")
            raise SearchFailure(f"{message} (HTTP {response.status_code})")
        try:
            results = response.json().get("web", {}).get("results", [])
            if not isinstance(results, list):
                raise ValueError()
            return results[:10]
        except (ValueError, AttributeError):
            raise SearchFailure("Search provider returned an invalid result") from None


def configured_search_key(root: Path):
    return os.getenv("BRAVE_SEARCH_API_KEY", "") or dotenv_values(root / ".env").get("BRAVE_SEARCH_API_KEY", "") or ""


def leads_from_results(partner: dict, results: list[dict]) -> list[dict]:
    from bs4 import BeautifulSoup
    leads, seen = [], set()
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            posting = canonical_posting(str(item.get("url", "")))
        except ValueError:
            continue
        if posting is None or posting[0] in seen:
            continue
        title = BeautifulSoup(str(item.get("title", "")), "html.parser").get_text(" ", strip=True)[:500]
        description = str(item.get("description", ""))
        extra = item.get("extra_snippets", [])
        if isinstance(extra, list):
            description += " " + " ".join(str(s) for s in extra[:5])
        evidence = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)[:5000]
        if not (CSHARP.search(title + evidence) or DOTNET.search(title + evidence)):
            continue
        seen.add(posting[0])
        leads.append({"id": hashlib.sha256((partner["id"] + posting[0]).encode()).hexdigest()[:24],
            "partner_id": partner["id"], "partner_name": partner["name"], "title": title or "Unknown role",
            "url": posting[0], "board": posting[1], "evidence": evidence,
            "classification": classify(title, evidence), "checked_at": utc_now(),
            "verification": "unreviewed", "employer": "", "role_type": "Unknown", "language": "Unconfirmed",
            "notes": "Search-result lead only; employer identity and current availability require review."})
    return leads


class LeadReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employer: str = Field(default="", max_length=300)
    role_type: str = Field(pattern=r"^(Internship/OJT|Full-time/other|Unknown)$")
    language: str = Field(pattern=r"^(C# confirmed|\.NET related|Unconfirmed)$")
    outcome: str = Field(pattern=r"^(reviewed|rejected|unavailable)$")
    notes: str = Field(default="", max_length=3000)


class MatcherStore:
    """Private state, atomic writes, and revision checks independent of the mail queue."""
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"directory": None, "searches": {}, "leads": {}}
        # Clean existing snapshots for display without changing partner IDs or
        # the source revision used by saved research and concurrency checks.
        for partner in (state.get("directory") or {}).get("partners", []):
            partner["name"] = clean_company_name(partner["name"])
        for lead in state.get("leads", {}).values():
            if "partner_name" in lead:
                lead["partner_name"] = clean_company_name(lead["partner_name"])
        return state

    def mutate(self, operation):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path.with_suffix(".write.lock")):
            state = self.load()
            operation(state)
            atomic_text(self.path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    def set_directory(self, directory):
        def update(state):
            previous = state.get("directory")
            if previous and previous["revision"] != directory["revision"]:
                archives = state.setdefault("archives", {})
                archives[previous["revision"]] = {"directory": previous, "searches": state["searches"], "leads": state["leads"]}
                restored = archives.pop(directory["revision"], None)
                state.update(searches=restored["searches"] if restored else {}, leads=restored["leads"] if restored else {})
            state["directory"] = directory
        self.mutate(update)

    def record_search(self, revision: str, partner_id: str, query: str, leads: list[dict]):
        def update(state):
            if not state.get("directory") or state["directory"]["revision"] != revision:
                raise QueueConflict("Partner directory changed during discovery; load the new directory")
            state["searches"][partner_id] = {"checked_at": utc_now(), "query": query, "lead_count": len(leads)}
            for lead in leads:
                previous = state["leads"].get(lead["id"])
                # A repeated search cannot silently erase a manual review or rejection.
                if previous and previous.get("verification") != "unreviewed":
                    continue
                state["leads"][lead["id"]] = lead
        self.mutate(update)

    def set_search_name(self, revision: str, partner_id: str, value: str):
        value = re.sub(r"\s+", " ", value).strip()
        if not value or len(value) > 200:
            raise ValueError("Use a search name between 1 and 200 characters")
        def update(state):
            directory = state.get("directory")
            if not directory or directory["revision"] != revision or partner_id not in {p["id"] for p in directory["partners"]}:
                raise QueueConflict("Partner directory changed; reopen the search-name editor")
            state.setdefault("search_names", {})[partner_id] = value
        self.mutate(update)

    def review(self, lead_id: str, changes: LeadReview, expected: dict):
        def update(state):
            lead = state["leads"].get(lead_id)
            if lead != expected:
                raise QueueConflict("Posting changed in another session; reopen its review")
            if changes.outcome == "reviewed" and not employer_matches(lead["partner_name"], changes.employer):
                raise ValueError("Employer differs from the directory company. Keep it rejected or unreviewed; related subsidiaries are not automatic matches")
            lead.update(**changes.model_dump(exclude={"outcome"}), verification=changes.outcome, reviewed_at=utc_now())
        self.mutate(update)
