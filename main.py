"""Optional local REST API and standalone company queue: uvicorn main:app."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from core import (Company, CompanyEdit, CompanyStore,
                  SUBJECT, render_template)

ROOT = Path(__file__).resolve().parent


class BulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=2000)


def create_app(data_path: Path | None = None) -> FastAPI:
    api = FastAPI(title="Internship Desk Company Queue")
    store = CompanyStore(data_path or ROOT / "companies.json")
    api.state.store = store

    def mutate(operation):
        try:
            return operation()
        except KeyError as exc:
            raise HTTPException(404, "Company not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Queue storage is unavailable; no change was confirmed") from exc

    @api.get("/api/companies", response_model=list[Company])
    def list_companies():
        return store.load()

    @api.put("/api/companies/{company_id}", response_model=list[Company])
    def edit_company(company_id: str, changes: CompanyEdit):
        return mutate(lambda: store.edit_company(company_id, changes))

    @api.delete("/api/companies/{company_id}", response_model=list[Company])
    def delete_company(company_id: str):
        return mutate(lambda: store.remove_companies([company_id], strict=True))

    @api.post("/api/companies/bulk-delete", response_model=list[Company])
    def bulk_delete(request: BulkDelete):
        return mutate(lambda: store.remove_companies(request.ids))

    @api.get("/api/preview/{company_id}")
    def preview(company_id: str):
        company = next((c for c in store.load() if c.id == company_id), None)
        if company is None:
            raise HTTPException(404, "Company not found")
        template_path = store.path.parent / "template.txt"
        template = template_path.read_text(encoding="utf-8") if template_path.exists() else (ROOT / "template.txt").read_text(encoding="utf-8")
        return {"to": company.hr_email, "subject": SUBJECT, "body": render_template(template, company)}

    @api.get("/", include_in_schema=False)
    def queue_page():
        return FileResponse(ROOT / "static" / "index.html")

    api.mount("/app/static", StaticFiles(directory=ROOT / "static"), name="fonts")
    api.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return api


app = create_app()
