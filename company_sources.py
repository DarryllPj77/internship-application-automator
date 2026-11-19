"""Directory ingestion and append-only queue import, independent of Google or UI."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from core import Company, EMAIL

MAX_IMPORT_BYTES = 10 * 1024 * 1024


class DirectoryMapping(BaseModel):
    first_data_row: int = Field(default=4, ge=1, le=5000)  # spreadsheet row numbers
    company: int = Field(default=1, ge=0, le=51)
    contact: int = Field(default=4, ge=0, le=51)
    position: int = Field(default=5, ge=0, le=51)
    email: int = Field(default=6, ge=0, le=51)
    industry: int | None = Field(default=2, ge=0, le=51)
    address: int | None = Field(default=3, ge=0, le=51)


def read_directory_file(raw: bytes, filename: str, worksheet: str | None = None):
    """Return available tab names and a bounded value matrix, without evaluating formulas."""
    if not raw or len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Choose a nonempty directory file up to 10 MB")
    if filename.lower().endswith(".csv"):
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        if len(rows) > 5000 or any(len(row) > 52 for row in rows):
            raise ValueError("Import supports up to 5,000 rows and 52 columns; split this directory first")
        return ["CSV"], rows
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Use a CSV or XLSX file")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 80 * 1024 * 1024:
            raise ValueError("Excel workbook expands beyond the 80 MB limit")
    from openpyxl import load_workbook
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    try:
        names = workbook.sheetnames
        sheet = workbook[worksheet or names[0]]
        if sheet.max_row and sheet.max_row > 5000 or sheet.max_column and sheet.max_column > 52:
            raise ValueError("Import supports up to 5,000 rows and 52 columns; export the needed range as CSV")
        rows = [["" if v is None else str(v) for v in row]
                for row in sheet.iter_rows(max_row=5000, max_col=min(sheet.max_column or 1, 52), values_only=True)]
        while rows and not any(rows[-1]):
            rows.pop()
        return names, rows
    finally:
        workbook.close()


def map_directory(rows: list[list], mapping: DirectoryMapping, source: str) -> list[dict]:
    candidates = []
    for number, row in enumerate(rows, 1):
        if number < mapping.first_data_row:
            continue
        def cell(index):
            return str(row[index] or "").strip() if index is not None and index < len(row) else ""
        name = cell(mapping.company)
        if not name:
            continue
        # Missing/invalid addresses remain visible for review, never guessed or silently sent.
        email = cell(mapping.email)
        candidates.append({"include": bool(EMAIL.fullmatch(email)), "company_name": name,
            "hr_email": email, "contact_person": cell(mapping.contact) or "Hiring Team",
            "contact_position": cell(mapping.position), "industry": cell(mapping.industry),
            "company_address": cell(mapping.address), "directory_source": source, "source_row": number})
    return candidates


def merge_directory(existing: list[Company], candidates: list[dict]) -> tuple[list[Company], int, int]:
    result = list(existing)
    seen = {c.hr_email.casefold() for c in existing}
    added = skipped = 0
    for row in candidates:
        if not row.get("include"):
            continue
        company = Company.model_validate({k: row[k] for k in (
            "company_name", "hr_email", "contact_person", "contact_position", "industry",
            "company_address", "directory_source", "source_row") if k in row})
        if company.hr_email.casefold() in seen:
            skipped += 1
            continue
        seen.add(company.hr_email.casefold())
        result.append(company)
        added += 1
    if len(result) > 10000:
        raise ValueError("Queue limit is 10,000 contacts")
    return result, added, skipped


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
