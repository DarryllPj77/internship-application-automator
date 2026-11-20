"""Source-backed company requirements search; excerpts never masquerade as full postings."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from bs4 import BeautifulSoup

from company_sources import utc_now
from core import atomic_text, exclusive_lock
from job_research import fetch_public_posting, MAX_PAGE_BYTES
from partner_matcher import canonical_posting, normalize_company, suggested_search_name

SOURCES = ["Company career pages", "JobStreet", "LinkedIn", "Indeed"]
DOMAINS = {"JobStreet": "ph.jobstreet.com", "LinkedIn": "linkedin.com", "Indeed": "ph.indeed.com"}
HEADINGS = r"requirements|qualifications|required(?: skills| qualifications)?|minimum qualifications|technical requirements|what you bring|what we(?:'|’)re looking for|what you need|who you are"
STOP = r"responsibilities|duties|benefits|about(?: us| the company)?|what we offer|how to apply|nice.to.have|preferred(?: skills| qualifications)?|optional(?: skills)?"


def requirements_query(company: str, role: str, location: str, sources: list[str], search_name=""):
    if not company.strip() or not sources or any(s not in SOURCES for s in sources):
        raise ValueError("Choose a company and at least one supported source")
    def clean(value):
        return re.sub(r'["\r\n]', " ", value).strip()[:200]
    phrase = f'"{clean(search_name or suggested_search_name(company))}" {clean(role)} {clean(location)} (requirements OR qualifications)'
    if "Company career pages" not in sources:
        phrase += " (" + " OR ".join("site:" + DOMAINS[s] for s in sources) + ")"
    else:
        phrase += " " + " ".join("-site:" + domain for source, domain in DOMAINS.items() if source not in sources)
    return phrase.strip()


def candidate_url(url: str):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return None
        if parsed.path.strip("/").split("/")[-1].casefold() in ("search", "search-results", "results", "jobs", "careers", "vacancies", "positions"):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host:
                return None
        posting = canonical_posting(url)
        if posting:
            return posting
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            match = re.fullmatch(r"/jobs/view/(?:[^/]*-)?(\d{5,})/?", parsed.path)
            return ("https://www.linkedin.com/jobs/view/" + match[1] + "/", "LinkedIn") if match else None
        if any(host == domain or host.endswith("." + domain) for domain in ("indeed.com", "jobstreet.com", "jobstreet.com.ph")):
            return None
        ats = host in ("jobs.lever.co", "jobs.ashbyhq.com", "jobs.smartrecruiters.com") and len(parsed.path.strip("/").split("/")) >= 2
        if not ats and not re.search(r"/(?:jobs?|careers?|vacancies|positions?|opportunities|j)/[^/?]+", parsed.path, re.I):
            return None
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, "")), "Company career pages"
    except ValueError:
        return None


def search_candidates(company: str, results: list[dict], sources: list[str]):
    found, seen = [], set()
    for item in results[:10]:
        if not isinstance(item, dict):
            continue
        source = candidate_url(str(item.get("url", "")))
        if not source or source[1] not in sources or source[0] in seen:
            continue
        seen.add(source[0])
        def text(value):
            return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
        extra = item.get("extra_snippets", [])
        excerpt = text(item.get("description", ""))
        if isinstance(extra, list):
            excerpt += "\n" + "\n".join(text(value) for value in extra[:5])
        found.append({"id": hashlib.sha256(source[0].encode()).hexdigest()[:24], "url": source[0],
            "source": source[1], "requested_company": company, "title": text(item.get("title", "Unknown role"))[:500],
            "excerpt": excerpt.strip()[:8000], "checked_at": utc_now()})
    return found


def extract_required_section(text: str):
    lines, selected, active = text.splitlines(), [], False
    for line in lines:
        value = re.sub(r"^[*•\-–—]\s+", "", line.strip().strip("# "))
        match = re.fullmatch(r"(?:" + HEADINGS + r")\s*(?::\s*(.*))?", value, re.I)
        if match:
            active = True
            if match[1]:
                selected.append(match[1])
            continue
        if re.fullmatch(r"(?:" + STOP + r")\s*:?.*", value, re.I):
            active = False
            continue
        if active:
            selected.append(line.strip())
    return "\n".join(selected).strip()[:20000]


def _plain(value):
    if isinstance(value, list):
        return "\n".join(_plain(item) for item in value)
    if isinstance(value, dict):
        return _plain(value.get("description") or value.get("name") or value.get("text") or "")
    return BeautifulSoup(str(value or ""), "html.parser").get_text("\n", strip=True)


def requirements_document(html: str, url: str):
    if not html or len(html.encode("utf-8")) > MAX_PAGE_BYTES:
        raise ValueError("Use an HTML posting up to 2 MB")
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    def walk(value):
        if isinstance(value, dict):
            kind = value.get("@type")
            if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                jobs.append(value)
            else:
                for child in value.values():
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(script.string or ""))
        except (ValueError, RecursionError):
            continue
    if len(jobs) > 1:
        raise ValueError("This page contains multiple jobs. Choose a specific posting or paste its requirements")
    heading = soup.find("h1") or soup.title
    title = heading.get_text(" ", strip=True) if heading else "Unknown role"
    employer = posted = expires = ""
    requirements = ""
    kind = "posting_section"
    if jobs:
        job = jobs[0]
        title = str(job.get("title") or title)
        organization = job.get("hiringOrganization", "")
        employer = _plain(organization.get("name", "") if isinstance(organization, dict) else organization)
        posted, expires = str(job.get("datePosted") or ""), str(job.get("validThrough") or "")
        requirements = "\n".join(_plain(job.get(field)) for field in (
            "qualifications", "skills", "experienceRequirements", "educationRequirements") if job.get(field))
        if requirements:
            kind = "structured_qualifications"
        else:
            requirements = extract_required_section(_plain(job.get("description")))
    else:
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        requirements = extract_required_section((soup.find("main") or soup).get_text("\n", strip=True))
    if not requirements.strip():
        raise ValueError("No explicit requirements section found. Open the source and paste the required qualifications")
    return {"url": url, "title": title[:500], "employer": employer[:300], "text": requirements[:20000],
            "evidence_type": kind, "checked_at": utc_now(), "posting_date": posted[:80], "expires": expires[:80]}


def read_requirements(candidate: dict):
    if candidate["source"] != "Company career pages":
        raise ValueError("Full automated reading is limited to public career pages. For this board, review the indexed excerpt or paste the posting text")
    html, final_url = fetch_public_posting(candidate["url"], blocked_domains=("indeed.com",))
    return requirements_document(html, final_url)


class RequirementsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"searches": {}, "documents": {}, "applied": {}}

    def save(self, section, key, value):
        if section not in ("searches", "documents", "applied"):
            raise ValueError("Unknown requirements storage section")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path.with_suffix(".write.lock")):
            state = self.load()
            state[section][key] = value
            atomic_text(self.path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    def apply(self, company: str, candidate: dict, text: str, evidence_type: str, *, employer_confirmed: bool):
        if not employer_confirmed or not company.strip() or not text.strip() or len(text) > 20000:
            raise ValueError("Confirm the company and review 1–20,000 characters of requirements before applying")
        if candidate["requested_company"] != company or not candidate_url(candidate["url"]):
            raise ValueError("This posting belongs to a different company search; select it again")
        record = {"review_id": uuid4().hex, "company_name": company, "title": candidate["title"],
            "url": candidate["url"], "text": text.strip(), "evidence_type": evidence_type,
            "checked_at": candidate["checked_at"], "reviewed_at": utc_now()}
        if candidate.get("content_url"):
            record["content_url"] = candidate["content_url"]
        self.save("applied", normalize_company(company), record)
        return record
