import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core import Company, CompanyEdit, CompanyStore, QueueConflict, atomic_text, exclusive_lock, run_batch
import asyncio
from types import SimpleNamespace
from main import create_app


class CompanyAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = CompanyStore(self.root / "companies.json")
        self.first = Company(company_name="First", hr_email="first@company.com", contact_person="HR", relevant_skills="Python", status="sent", last_result="existing-message-id")
        self.second = Company(company_name="Second", hr_email="second@company.com", contact_person="Recruiter", relevant_skills="SQL")
        self.store._write([self.first, self.second])
        atomic_text(self.root / "template.txt", "Hello {contact_person} at {company_name}: {relevant_skills}")
        self.client = TestClient(create_app(self.store.path))
        self.addCleanup(self.client.close)

    def changes(self, **overrides):
        return {**{k: getattr(self.first, k) for k in ("company_name", "hr_email", "contact_person", "relevant_skills", "status")}, **overrides}

    def test_edit_validates_defaults_and_preserves_identity_and_result(self):
        result = self.client.put(f"/api/companies/{self.first.id}", json=self.changes(company_name=" Updated ", hr_email="new@company.com", contact_person="  ", relevant_skills="", status="Pending"))
        self.assertEqual(result.status_code, 200, result.text)
        rows = result.json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], self.first.id)
        self.assertEqual(rows[0]["company_name"], "Updated")
        self.assertEqual(rows[0]["hr_email"], "new@company.com")
        self.assertEqual(rows[0]["contact_person"], "Hiring Team")
        self.assertEqual(rows[0]["relevant_skills"], "software development")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["last_result"], "existing-message-id")
        self.assertEqual(self.store.load()[0].model_dump(), rows[0])
        preview = self.client.get(f"/api/preview/{self.first.id}").json()
        self.assertEqual(preview["to"], "new@company.com")
        self.assertIn("Hiring Team at Updated: software development", preview["body"])

    def test_invalid_edits_do_not_write(self):
        original = self.store.path.read_bytes()
        for changes in (self.changes(company_name=""), self.changes(hr_email="not-an-address"), self.changes(status="unknown"), self.changes(id="replacement-id")):
            response = self.client.put(f"/api/companies/{self.first.id}", json=changes)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.store.path.read_bytes(), original)

    def test_single_delete_persists_and_missing_company_is_404(self):
        response = self.client.delete(f"/api/companies/{self.first.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [self.second.id])
        self.assertEqual([row.id for row in self.store.load()], [self.second.id])
        self.assertEqual(self.client.delete(f"/api/companies/{self.first.id}").status_code, 404)
        self.assertEqual(self.client.put("/api/companies/missing", json=self.changes()).status_code, 404)

    def test_bulk_delete_matches_ids_once_and_handles_empty_queue(self):
        response = self.client.post("/api/companies/bulk-delete", json={"ids": [self.first.id, self.first.id, "missing", self.second.id]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.client.get("/api/companies").json(), [])
        for payload in ({"ids": []}, {"ids": "not-a-list"}, {"ids": [5]}, {}):
            self.assertEqual(self.client.post("/api/companies/bulk-delete", json=payload).status_code, 422)

    def test_mutations_are_blocked_during_batch(self):
        original = self.store.path.read_bytes()
        with exclusive_lock(self.store.batch_lock):
            responses = [self.client.put(f"/api/companies/{self.first.id}", json=self.changes()),
                         self.client.delete(f"/api/companies/{self.first.id}"),
                         self.client.post("/api/companies/bulk-delete", json={"ids": [self.first.id]})]
        self.assertTrue(all(response.status_code == 409 for response in responses))
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_uncertain_status_cannot_be_reset_without_reconciliation(self):
        self.store.update(self.first.id, needs_review=True)
        response = self.client.put(f"/api/companies/{self.first.id}", json=self.changes(status="pending"))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.store.load()[0].needs_review)

    def test_stale_storage_edits_cannot_overwrite_newer_data(self):
        previous = self.store.load()
        self.store.update(self.second.id, status="drafted")
        with self.assertRaises(QueueConflict):
            self.store.edit_company(self.first.id, CompanyEdit(**self.changes()), expected=previous)
        with self.assertRaises(QueueConflict):
            self.store.remove_companies([self.first.id], expected=previous)
        self.assertEqual(self.store.load()[1].status, "drafted")

    def test_batch_cannot_start_while_a_queue_write_is_in_progress(self):
        pdf = self.root / "CV.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        client = SimpleNamespace(connect=lambda: self.fail("Mail must not start during a queue write"))
        with exclusive_lock(self.store.path.with_suffix(".write.lock")):
            with self.assertRaises(ValueError):
                asyncio.run(run_batch(self.store, client, [self.first], "Hello", str(pdf), "draft", lambda *args: None))
        self.assertFalse(self.store.batch_lock.exists())

    def test_static_queue_page_and_fonts_are_served(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('class="actions-col">Actions', page.text)
        self.assertIn('id="edit-modal"', page.text)
        self.assertIn('/api/companies/bulk-delete', page.text)
        self.assertEqual(self.client.get('/app/static/fonts/inter-latin.woff2').status_code, 200)
