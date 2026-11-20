"""Local data, rendering, validation, and observable batch execution."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import random
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUBJECT = "FEU TECH - DARRYLL PAJAGANAS - Internship Application - BSCSSE - 2TSY2627 - Internship 1"
FIELDS = ("company_name", "hr_email", "contact_person", "relevant_skills")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")
MAX_CV_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_CONTACT = "Hiring Team"
DEFAULT_SKILLS = "software development"


class QueueConflict(ValueError):
    """A queue change cannot safely be applied to current storage."""


def parse_recipients(value) -> list[str]:
    """Accept plain addresses separated by commas, semicolons or newlines."""
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[,;\n]", value)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Recipients must be email addresses")
    result, seen = [], set()
    for item in value:
        address = item.strip()
        if not address:
            continue
        if not EMAIL.fullmatch(address):
            raise ValueError(f"Invalid copy recipient: {address!r}")
        if address.casefold() not in seen:
            result.append(address)
            seen.add(address.casefold())
    if len(result) > 50:
        raise ValueError("Use at most 50 addresses per copy field")
    return result


class EmailSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)

    @field_validator("cc", "bcc", mode="before")
    @classmethod
    def valid_recipients(cls, value):
        return parse_recipients(value)

    @model_validator(mode="after")
    def distinct_copy_fields(self):
        if {a.casefold() for a in self.cc} & {a.casefold() for a in self.bcc}:
            raise ValueError("An address cannot appear in both CC and BCC")
        return self


def load_email_settings(path: Path) -> EmailSettings:
    return EmailSettings.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else EmailSettings()


def save_email_settings(path: Path, settings: EmailSettings):
    atomic_text(path, settings.model_dump_json(indent=2) + "\n")


class Opportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    technologies: list[str] = Field(default_factory=list, max_length=100)
    source_url: str = Field(max_length=2048)
    checked_at: str = Field(max_length=80)
    posting_date: str = Field(default="", max_length=80)
    expires: str = Field(default="", max_length=80)
    verification: Literal["unverified", "reviewed"] = "unverified"
    notes: str = Field(default="", max_length=5000)

    @field_validator("source_url")
    @classmethod
    def public_source(cls, value):
        from urllib.parse import urlparse
        parsed = urlparse(value.strip())
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTP(S) posting URL without credentials")
        return value.strip()


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    company_name: str
    hr_email: str
    contact_person: str = DEFAULT_CONTACT
    relevant_skills: str = DEFAULT_SKILLS
    status: Literal["pending", "drafted", "sent", "failed"] = "pending"
    needs_review: bool = False
    last_result: str = ""
    directory_source: str = ""
    source_row: int | None = None
    contact_position: str = ""
    industry: str = ""
    company_address: str = ""
    opportunities: list[Opportunity] = Field(default_factory=list, max_length=100)

    @field_validator("contact_person", "relevant_skills", mode="before")
    @classmethod
    def default_blank_details(cls, value, info):
        if value is None or isinstance(value, str) and not value.strip():
            return DEFAULT_CONTACT if info.field_name == "contact_person" else DEFAULT_SKILLS
        return value

    @field_validator("status", mode="before")
    @classmethod
    def lower_status(cls, value):
        return str(value).lower()

    @field_validator(*FIELDS)
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Company fields cannot be empty")
        return value

    @field_validator("hr_email")
    @classmethod
    def valid_email(cls, value):
        if not EMAIL.fullmatch(value):
            raise ValueError("Enter one valid HR email address")
        return value


class CompanyEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str
    hr_email: str
    contact_person: str = DEFAULT_CONTACT
    relevant_skills: str = DEFAULT_SKILLS
    status: Literal["pending", "drafted", "sent", "failed"] = "pending"

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = Company.model_validate(value)
        return {**value, **{field: getattr(normalized, field) for field in (*FIELDS, "status")}}


def validate_pdf(value: str) -> Path:
    if not value.strip():
        raise ValueError("Choose a CV PDF first")
    path = Path(os.path.expandvars(value)).expanduser().resolve()
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError("CV must be an existing .pdf file")
    with path.open("rb") as file:
        if file.read(5) != b"%PDF-":
            raise ValueError("CV file does not have a PDF signature")
    return path


def save_uploaded_cv(directory: Path, filename: str, data: bytes) -> Path:
    """Save an immutable local PDF outside the publicly served static directory."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if Path(name).suffix.lower() != ".pdf":
        raise ValueError("Upload a .pdf file")
    if not data or len(data) > MAX_CV_UPLOAD_BYTES:
        raise ValueError("Upload a nonempty PDF no larger than 20 MB")
    if not data.startswith(b"%PDF-"):
        raise ValueError("The uploaded file does not have a PDF signature")
    stem = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).stem).strip(" .")[:100] or "CV"
    if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        stem = "CV-" + stem
    # A changed PDF gets a different directory, preserving confirmed attachments.
    folder = directory.resolve() / hashlib.sha256(data).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (stem + ".pdf")
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError("The saved upload was modified; restore or remove it before uploading again")
        return validate_pdf(str(target))
    fd, temporary = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return validate_pdf(str(target))


def format_skill_list(value: str) -> str:
    """Add a final conjunction to comma-separated skills without changing stored data."""
    # Plain-text mail readers can auto-link dotted names such as ASP.NET.
    # Use spaces within skill names; keep .NET and numeric versions intact.
    value = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", " ", value)
    if "," not in value:
        return value
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return value
    items[-1] = re.sub(r"^and\s+", "", items[-1], flags=re.I)
    # Preserve manually written phrases such as 'C#, SQL and database design'.
    if re.search(r"\band\b", items[-1], re.I):
        return value
    if len(items) < 2:
        return items[0]
    if len(items) == 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def render_template(template: str, company: Company) -> str:
    # Single pass: braces in company data must never introduce substitutions.
    values = {field: getattr(company, field) for field in FIELDS}
    values["relevant_skills"] = format_skill_list(company.relevant_skills)
    return PLACEHOLDER.sub(
        lambda match: values.get(match.group()[1:-1], match.group()), template
    )


def email_payload(company: Company, template: str, cv_path: str, *, cc=None, bcc=None) -> dict:
    company = Company.model_validate(company.model_dump())
    path = validate_pdf(cv_path)
    body = render_template(template, company)
    if not body.strip():
        raise ValueError("Email body cannot be empty")
    if PLACEHOLDER.search(body) or "{" in body or "}" in body:
        raise ValueError("Resolve all {placeholders} and stray braces before continuing")
    if company.hr_email.lower().endswith((".example", ".invalid", ".test")):
        raise ValueError("Replace the sample/reserved HR email with a real recipient")
    settings = EmailSettings(cc=cc, bcc=bcc)
    payload = {"to": [company.hr_email], "cc": settings.cc, "subject": SUBJECT,
               "body": body, "attachments": [str(path)]}
    if settings.bcc:
        payload["bcc"] = settings.bcc
    return payload


@contextmanager
def exclusive_lock(path: Path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"Another operation holds {path.name}. See README recovery steps.") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


def atomic_text(path: Path, value: str):
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class CompanyStore:
    def __init__(self, path: Path):
        self.path = path
        self.batch_lock = path.with_suffix(".batch.lock")

    def load(self) -> list[Company]:
        rows = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list):
            raise ValueError("companies.json must contain a JSON array")
        # External hand-written rows need stable identities across reloads too.
        companies = [Company.model_validate({"id": uuid5(NAMESPACE_URL, str(row.get("hr_email", "")).casefold()).hex,
                                             **row}) for row in rows]
        if len({c.id for c in companies}) != len(companies):
            raise ValueError("Company IDs must be unique")
        return companies

    def _write(self, companies):
        atomic_text(self.path, json.dumps([c.model_dump() for c in companies], indent=2, ensure_ascii=False) + "\n")

    def replace(self, companies: list[Company], expected: list[Company]):
        with exclusive_lock(self.path.with_suffix(".write.lock")):
            if self.batch_lock.exists():
                raise QueueConflict("A batch is running. Company edits are temporarily locked.")
            if self.load() != expected:
                raise QueueConflict("Company data changed in another session. Reload before editing.")
            if len({c.id for c in companies}) != len(companies):
                raise ValueError("Company IDs must be unique")
            self._write(companies)

    def edit_company(self, company_id: str, changes: CompanyEdit, *, expected=None):
        original = self.load() if expected is None else expected
        company = next((c for c in original if c.id == company_id), None)
        if company is None:
            raise KeyError("Company not found")
        if company.needs_review and changes.status != company.status:
            raise QueueConflict("Check Gmail and reconcile the uncertain outcome before changing this status")
        replacement = Company.model_validate({**company.model_dump(), **changes.model_dump()})
        updated = [replacement if c.id == company_id else c for c in original]
        self.replace(updated, original)
        return updated

    def remove_companies(self, ids: list[str], *, strict=False, expected=None):
        original = self.load() if expected is None else expected
        requested = set(ids)
        if strict and requested - {c.id for c in original}:
            raise KeyError("Company not found")
        updated = [c for c in original if c.id not in requested]
        self.replace(updated, original)
        return updated

    def update(self, company_id: str, **changes):
        with exclusive_lock(self.path.with_suffix(".write.lock")):
            companies = self.load()
            row = next(c for c in companies if c.id == company_id)
            updated = Company.model_validate({**row.model_dump(), **changes})
            companies[companies.index(row)] = updated
            self._write(companies)


def import_companies(raw: bytes, filename: str, existing: list[Company]) -> list[Company]:
    text = raw.decode("utf-8-sig")
    rows = json.loads(text) if filename.lower().endswith(".json") else list(csv.DictReader(io.StringIO(text)))
    if not isinstance(rows, list) or not rows or len(rows) > 2000:
        raise ValueError("Import must contain 1–2000 company rows")
    result = list(existing)
    seen = {c.hr_email.casefold() for c in existing}
    for row in rows:
        # Imports cannot overwrite sent/recovery status or reuse internal IDs.
        company = Company(**{key: row.get(key, "") for key in FIELDS})
        if company.hr_email.casefold() in seen:
            continue
        seen.add(company.hr_email.casefold())
        result.append(company)
    return result


async def run_batch(store, client, companies, template, cv_path, mode, emit, sleep=asyncio.sleep, *, cc=None, bcc=None):
    """emit receives log/progress/countdown events; no automatic retry of mail calls."""
    if mode not in ("draft", "send"):
        raise ValueError("Unknown execution mode")
    if not companies:
        raise ValueError("Select at least one company")
    if len({c.id for c in companies}) != len(companies):
        raise ValueError("Duplicate selections are not allowed")
    if len({c.hr_email.casefold() for c in companies}) != len(companies):
        raise ValueError("Selected companies share an HR email; choose only one row per recipient")
    # Validate the entire reviewed snapshot before spawning a server or sending.
    payloads = [email_payload(c, template, cv_path, cc=cc, bcc=bcc) for c in companies]
    with exclusive_lock(store.batch_lock):
        # Synchronize startup with queue mutations already inside their write lock.
        with exclusive_lock(store.path.with_suffix(".write.lock")):
            current = {c.id: c for c in store.load()}
            for company in companies:
                if current.get(company.id) != company:
                    raise ValueError("Company data changed since confirmation; preview again")
                if company.needs_review:
                    raise ValueError(f"Review the previous uncertain outcome for {company.company_name}")
        async with client.connect() as connection:
            connection.require_tool(mode)
            # Reject unsupported copy fields before any Gmail operation starts.
            if hasattr(connection, "validate_payload"):
                for payload in payloads:
                    connection.validate_payload(mode, payload)
            emit("log", f"Connected · {mode} tool: {connection.require_tool(mode).name}")
            for index, (company, payload) in enumerate(zip(companies, payloads)):
                # Durable marker BEFORE calling Gmail survives app/process interruption.
                store.update(company.id, needs_review=True,
                             last_result="Operation started; verify Gmail if interrupted.")
                emit("log", f"Processing {company.company_name} <{company.hr_email}>")
                try:
                    result = await connection.deliver(mode, payload)
                except Exception as exc:
                    store.update(company.id, status="failed", needs_review=True,
                                 last_result=f"Uncertain/failed: {exc}")
                    emit("log", f"FAILED / REVIEW REQUIRED · {company.company_name}: {exc}")
                    emit("progress", (index + 1) / len(companies))
                    # Transport failures may invalidate the session. Stop without retry.
                    break
                else:
                    store.update(company.id, status="drafted" if mode == "draft" else "sent",
                                 needs_review=False, last_result=result)
                    emit("log", f"{'DRAFTED' if mode == 'draft' else 'SENT'} · {company.company_name}\nMCP: {result}")
                emit("progress", (index + 1) / len(companies))
                if mode == "send" and index < len(companies) - 1:
                    for seconds in range(random.randint(15, 30), 0, -1):
                        emit("countdown", seconds)
                        await sleep(1)
                    emit("countdown", 0)
