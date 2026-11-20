"""Bounded public posting reader and deterministic suggestions; no account scraping or LLM."""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from company_sources import utc_now
from core import Opportunity

MAX_PAGE_BYTES = 2 * 1024 * 1024
TECHNOLOGIES = {
    "C#": r"(?<!\w)c\s*#", ".NET": r"(?<!\w)\.net\b|\basp\.?net\b",
    "ASP.NET": r"\basp\.?net\b", "JavaScript": r"\bjavascript\b", "TypeScript": r"\btypescript\b",
    "Python": r"\bpython\b", "Java": r"\bjava\b", "PHP": r"\bphp\b",
    "C++": r"(?<!\w)c\+\+", "Go": r"\bgolang\b", "Rust": r"\brust\b",
    "React": r"\breact(?:\.js|js)?\b", "Angular": r"\bangular\b", "Vue": r"\bvue(?:\.js|js)?\b",
    "Next.js": r"\bnext\.?js\b", "Node.js": r"\bnode\.?js\b", "SQL": r"\bsql\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b", "MySQL": r"\bmysql\b", "SQL Server": r"\bsql server\b",
    "MongoDB": r"\bmongodb\b", "Redis": r"\bredis\b", "HTML": r"\bhtml5?\b", "CSS": r"\bcss3?\b",
    "Tailwind CSS": r"\btailwind\b", "Git": r"\bgit\b", "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b", "AWS": r"\baws\b|amazon web services",
    "Azure": r"\bazure\b", "Google Cloud": r"\bgcp\b|google cloud", "Flutter": r"\bflutter\b",
    "Django": r"\bdjango\b", "FastAPI": r"\bfastapi\b", "Laravel": r"\blaravel\b",
    "Spring Boot": r"\bspring boot\b", "REST APIs": r"\brest(?:ful)?\b",
}


def fetch_public_posting(url: str, *, blocked_domains=()) -> tuple[str, str]:
    """HTTPS only. Pin each connection to a validated public IP, including redirects."""
    current = url.strip()
    for _ in range(5):
        parsed = urlsplit(current)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Automatic fetching accepts public HTTPS posting URLs on port 443 only")
        host = parsed.hostname
        if any(host == domain or host.endswith("." + domain) for domain in ("linkedin.com", "jobstreet.com", "jobstreet.com.ph", *blocked_domains)):
            raise ValueError("Automatic full-page reading is disabled for this job board. Open the source and paste its required qualifications")
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = [address[4][0] for address in addresses]
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError("Posting URLs must resolve exclusively to public internet addresses")
        # Connect to the verified IP; TLS certificate/SNI and Host still use the original hostname.
        connection = http.client.HTTPSConnection(host, timeout=12, context=ssl.create_default_context())
        try:
            sock = socket.create_connection((ips[0], 443), timeout=12)
            try:
                connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            except Exception:
                sock.close()
                raise
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request("GET", target, headers={"User-Agent": "InternshipDesk/1.0 (local posting preview)",
                                                       "Accept": "text/html", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Posting redirected without a destination")
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ValueError(f"Posting returned HTTP {response.status}. Paste its text instead")
            if "text/html" not in response.getheader("Content-Type", "").lower():
                raise ValueError("Posting must return an HTML page; paste its text instead")
            if response.getheader("Content-Encoding", "identity").lower() not in ("identity", ""):
                raise ValueError("Unsupported page encoding; paste the posting text instead")
            raw = response.read(MAX_PAGE_BYTES + 1)
            if len(raw) > MAX_PAGE_BYTES:
                raise ValueError("Posting exceeds the 2 MB page limit")
            return raw.decode("utf-8", errors="replace"), current
        finally:
            connection.close()
    raise ValueError("Too many posting redirects")


def posting_suggestion(content: str, source_url: str, *, is_html=False) -> Opportunity:
    """Keywords are mentions, not guaranteed requirements, vacancies, or applicant skills."""
    from bs4 import BeautifulSoup
    if not content.strip() or len(content.encode("utf-8")) > MAX_PAGE_BYTES:
        raise ValueError("Provide posting text up to 2 MB")
    title = posted = expires = ""
    if is_html:
        soup = BeautifulSoup(content, "html.parser")
        def find_job(value):
            if isinstance(value, dict):
                kind = value.get("@type", [])
                if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                    return value
                for nested in value.values():
                    job = find_job(nested)
                    if job:
                        return job
            elif isinstance(value, list):
                for nested in value:
                    job = find_job(nested)
                    if job:
                        return job
            return None
        job = None
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                job = find_job(json.loads(script.string or ""))
            except (ValueError, RecursionError):
                continue
            if job:
                break
        heading = soup.find("h1") or soup.title
        title = heading.get_text(" ", strip=True) if heading else ""
        if job:
            title = str(job.get("title") or title)
            posted, expires = str(job.get("datePosted") or ""), str(job.get("validThrough") or "")
            text = BeautifulSoup(str(job.get("description") or ""), "html.parser").get_text(" ", strip=True)
        else:
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = (soup.find("main") or soup).get_text("\n", strip=True)
    else:
        text = content
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = next((line for line in lines[:15] if re.search(r"\bintern(?:ship)?\b", line, re.I)), lines[0] if lines else "")
    return Opportunity(title=(title or "Unknown role — review source")[:300],
        technologies=[name for name, pattern in TECHNOLOGIES.items() if re.search(pattern, text, re.I)],
        source_url=source_url, checked_at=utc_now(), posting_date=posted[:80], expires=expires[:80],
        notes="Suggested from source text; technologies are mentions. Confirm company, role availability, and requirements.")
