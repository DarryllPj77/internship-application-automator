"""Local, source-labelled active-partner membership; never changes the email queue."""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from company_sources import utc_now
from core import atomic_text, clean_company_name, exclusive_lock
from partner_matcher import normalize_company
from sheets_client import spreadsheet_reference


class ActivePartnerList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str
    worksheet: str = Field(min_length=1)
    first_data_row: int = Field(ge=1, le=5000)
    company_column: int = Field(ge=0, le=51)
    checked_at: str
    company_names: list[str] = Field(min_length=1, max_length=5000)

    @property
    def names(self):
        return {name for value in self.company_names if (name := normalize_company(value))}


def build_active_list(rows, *, source_url, worksheet, first_data_row=4, company_column=1):
    spreadsheet_reference(source_url)
    if not 1 <= first_data_row <= 5000 or not 0 <= company_column <= 51:
        raise ValueError("Choose a valid first company row and company-name column")
    names = {}
    for row in rows[first_data_row - 1:5000]:
        if company_column >= len(row):
            continue
        name = clean_company_name(str(row[company_column] or ""))
        normalized = normalize_company(name)
        if normalized:
            names.setdefault(normalized, name)
    if not names:
        raise ValueError("No company names found. Check the first data row and company column; the previous list was kept")
    return ActivePartnerList(source_url=source_url, worksheet=worksheet, first_data_row=first_data_row,
        company_column=company_column, checked_at=utc_now(), company_names=list(names.values()))


def load_active_list(path: Path):
    if not path.exists():
        return None
    return ActivePartnerList.model_validate_json(path.read_text(encoding="utf-8"))


def save_active_list(path: Path, snapshot: ActivePartnerList):
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path.with_suffix(".write.lock")):
        atomic_text(path, snapshot.model_dump_json(indent=2) + "\n")
