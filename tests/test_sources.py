import io
import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from streamlit.testing.v1 import AppTest

from company_sources import DirectoryMapping, map_directory, merge_directory, read_directory_file, suggest_directory_mapping
from core import Company, CompanyEdit, CompanyStore, atomic_text
from job_research import posting_suggestion, fetch_public_posting
from sheets_client import SheetsReader, spreadsheet_reference, save_token

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://docs.google.com/spreadsheets/d/test-id/edit?gid=42#gid=42"


class DirectoryTests(unittest.TestCase):
    def matrix(self):
        return [["", "Note: contact school for clarification"],
                ["", "INDUSTRY PARTNER", "TYPE OF INDUSTRY", "ADDRESS", "POINT OF CONTACT 1"],
                ["", "", "", "", "Name", "Position", "Email", "Name", "Position", "Email"],
                [1, "Software Co", "Software", "Manila", "A Recruiter", "HR Manager", "hr@company.test", "B Recruiter", "HR", "second@company.test"],
                [2, "Missing Email Co", "Software", "", "Another POC", "Director", ""]]

    def test_multirow_header_and_poc_mapping_and_missing_email(self):
        candidates = map_directory(self.matrix(), DirectoryMapping(), SOURCE)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_row"], 4)
        self.assertEqual(candidates[0]["contact_position"], "HR Manager")
        self.assertTrue(candidates[0]["include"])
        self.assertFalse(candidates[1]["include"])
        more = map_directory(self.matrix(), DirectoryMapping(contact=7, position=8, email=9), SOURCE)
        self.assertEqual(more[0]["hr_email"], "second@company.test")

    def test_import_preserves_sent_rows_and_skips_duplicate_case(self):
        existing = Company(company_name="My edit", hr_email="HR@company.test", status="sent", last_result="gmail-id")
        rows = map_directory(self.matrix(), DirectoryMapping(), SOURCE)
        updated, added, skipped = merge_directory([existing], rows)
        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(updated[0].model_dump(exclude={"directory_names", "directory_sources"}), existing.model_dump(exclude={"directory_names", "directory_sources"}))
        self.assertEqual(updated[0].directory_names, ["Software Co"])
        rows[1].update(include=True, hr_email="new@company.test")
        updated, added, skipped = merge_directory([existing], rows)
        self.assertEqual((added, skipped), (1, 1))
        self.assertEqual(updated[0].last_result, "gmail-id")
        self.assertEqual(updated[1].status, "pending")
        self.assertEqual(updated[1].relevant_skills, "software development")

    def test_invalid_checked_email_does_not_modify_existing(self):
        existing = [Company(company_name="Existing", hr_email="existing@company.test")]
        rows = map_directory(self.matrix(), DirectoryMapping(), SOURCE)
        rows[1]["include"] = True
        with self.assertRaises(ValueError):
            merge_directory(existing, rows)
        self.assertEqual(len(existing), 1)

    def test_csv_and_xlsx_tabs_and_formula_cache(self):
        from openpyxl import Workbook
        _, rows = read_directory_file(b"company,email\nOne,hr@one.test", "directory.csv")
        self.assertEqual(rows[1][0], "One")
        book = Workbook()
        book.active.title = "First"
        book.active.append(["One", "=1+1"])
        book.create_sheet("Second").append(["Two", "contact@two.test"])
        output = io.BytesIO()
        book.save(output)
        names, rows = read_directory_file(output.getvalue(), "directory.xlsx", "Second")
        self.assertEqual(names, ["First", "Second"])
        self.assertEqual(rows, [["Two", "contact@two.test"]])
        _, rows = read_directory_file(output.getvalue(), "directory.xlsx", "First")
        self.assertEqual(rows[0][1], "")  # formulas are never executed
        with self.assertRaises(ValueError):
            read_directory_file(b"", "empty.csv")

    def test_directory_provenance_survives_queue_edit(self):
        rows = map_directory(self.matrix(), DirectoryMapping(), SOURCE)
        result, _, _ = merge_directory([], rows)
        with tempfile.TemporaryDirectory() as directory:
            store = CompanyStore(Path(directory) / "companies.json")
            store._write(result)
            company = store.load()[0]
            store.edit_company(company.id, CompanyEdit(company_name="Updated", hr_email=company.hr_email))
            self.assertEqual(store.load()[0].directory_source, SOURCE)
            self.assertEqual(store.load()[0].contact_position, "HR Manager")


class SheetsTests(unittest.TestCase):
    def test_first_connection_creates_private_token_directory(self):
        credentials = MagicMock()
        credentials.to_json.return_value = '{"token": "test-only"}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".local" / "sheets-token.json"
            save_token(path, credentials)
            self.assertEqual(json.loads(path.read_text())["token"], "test-only")

    def test_reference_and_gid(self):
        self.assertEqual(spreadsheet_reference(SOURCE), ("test-id", 42))
        for url in ("http://docs.google.com/spreadsheets/d/x", "https://evil.test/spreadsheets/d/x", "https://docs.google.com/spreadsheets/d/x?gid=no"):
            with self.assertRaises(ValueError):
                spreadsheet_reference(url)

    def test_read_only_bounded_range_and_escaped_tab(self):
        service = MagicMock()
        service.spreadsheets().values().get().execute.return_value = {"values": [["Company"]]}
        reader = SheetsReader()
        with patch.object(reader, "service", return_value=service):
            self.assertEqual(reader.read(SOURCE, "Team's tab"), [["Company"]])
        self.assertEqual(service.spreadsheets().values().get.call_args.kwargs["range"], "'Team''s tab'!A1:AZ5000")
        self.assertTrue(service.close.called)

    def test_missing_auth_does_not_open_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "not connected"):
                SheetsReader(Path(directory) / "absent.json").service()


class ResearchTests(unittest.TestCase):
    def test_plaintext_suggestion_is_unverified_and_not_applicant_skills(self):
        result = posting_suggestion("Software Engineering Intern\nC#, ASP.NET Core, PostgreSQL and React. Internet research.", "https://company.test/jobs/1")
        self.assertEqual(result.title, "Software Engineering Intern")
        self.assertIn("C#", result.technologies)
        self.assertIn(".NET", result.technologies)
        self.assertIn("PostgreSQL", result.technologies)
        self.assertEqual(result.verification, "unverified")
        self.assertTrue(result.checked_at)
        unknown = posting_suggestion("Intern\nPerform general office duties and internet research.", "https://company.test/jobs/2")
        self.assertEqual(unknown.technologies, [])

    def test_jobposting_structured_data_ignores_navigation_mentions(self):
        html = '<h1>Careers</h1><nav>Python</nav><script type="application/ld+json">' + json.dumps({"@graph": [{"@type": "JobPosting", "title": "Backend Intern", "description": "<p>Java and Spring Boot</p>", "datePosted": "2026-11-18", "validThrough": "2026-12-01"}]}) + '</script>'
        result = posting_suggestion(html, "https://company.test/jobs/1", is_html=True)
        self.assertEqual(result.title, "Backend Intern")
        self.assertEqual(result.technologies, ["Java", "Spring Boot"])
        self.assertEqual(result.expires, "2026-12-01")

    def test_local_and_account_scraping_fetches_are_blocked(self):
        for url in ("file:///etc/passwd", "http://company.test", "https://user:pass@company.test", "https://linkedin.com/jobs/view/1", "https://www.jobstreet.com.ph/job/1"):
            with self.assertRaises(ValueError):
                fetch_public_posting(url)
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"):
            with patch("job_research.socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]):
                with self.assertRaises(ValueError):
                    fetch_public_posting("https://company.test/jobs/1")

    def test_redirect_to_private_host_is_revalidated(self):
        response = MagicMock(status=302)
        response.getheader.return_value = "https://internal.test/"
        connection = MagicMock()
        connection.getresponse.return_value = response
        public = [(2, 1, 6, "", ("8.8.8.8", 443))]
        private = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch("job_research.socket.getaddrinfo", side_effect=[public, private]), \
             patch("job_research.socket.create_connection"), \
             patch("job_research.ssl.create_default_context"), \
             patch("job_research.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaises(ValueError):
                fetch_public_posting("https://company.test/jobs/1")
        self.assertTrue(connection.close.called)

    def test_reviewed_research_persists_without_changing_status_or_skills(self):
        company = Company(company_name="Company", hr_email="hr@company.test", status="sent", relevant_skills="C#")
        result = posting_suggestion("Intern\nPython", "https://company.test/jobs/1")
        company.opportunities = [result.model_copy(update={"verification": "reviewed"})]
        with tempfile.TemporaryDirectory() as directory:
            store = CompanyStore(Path(directory) / "companies.json")
            store._write([company])
            saved = store.load()[0]
            self.assertEqual(saved.status, "sent")
            self.assertEqual(saved.relevant_skills, "C#")
            self.assertEqual(saved.opportunities[0].technologies, ["Python"])


class SourcesUITests(unittest.TestCase):
    def test_active_import_detects_layout_preserves_existing_and_refreshes_membership(self):
        from active_partners import load_active_list
        from partner_matcher import normalize_company
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CompanyStore(root / "companies.json")
            existing = Company(company_name="ABS-CBN Film Productions, Inc. (AFPI)",
                hr_email="hr@abs.test", status="sent", relevant_skills="C#", last_result="receipt")
            store._write([existing])
            atomic_text(root / "template.txt", "Hello {company_name}")
            rows = [[], ["", "INDUSTRY PARTNER", "TYPE OF INDUSTRY", "COMPANY ADDRESS", "GENERIC HR EMAIL ADDRESS", "POINT OF CONTACT (POC) 1"],
                    ["", "", "", "", "", "Name", "Position", "Email"],
                    [1, "ABS CBN Film Productions", "Media", "Manila", "HR@abs.test", "Recruiter", "HR", "poc@abs.test"],
                    [2, "Active Only Co", "Software", "Manila", "", "Another recruiter", "HR", "hr@active.test"],
                    [3, "Missing email", "", "", "", "", "", ""]]
            mapping = suggest_directory_mapping(rows)
            self.assertEqual((mapping.email, mapping.contact, mapping.position, mapping.fallback_email), (4, 5, 6, 7))
            app = self.dashboard(root)
            app.session_state.directory_source_mode = "Upload Excel / CSV"
            def staged_upload(disabled):
                import streamlit as st
                st.session_state.directory_matrix = {"mode": "Upload Excel / CSV", "rows": rows,
                    "source": SOURCE + " | ACTIVE INDUSTRY PARTNERS", "url": SOURCE, "title": "ACTIVE INDUSTRY PARTNERS"}
            with patch("sources_ui._uploaded_source", side_effect=staged_upload):
                app.run()
                for _ in range(2):
                    next(b for b in app.button if b.label == "Select all valid contacts").click().run()
                    next(b for b in app.button if b.label == "Add reviewed contacts to queue").click().run()
                    self.assertFalse(app.exception)
                saved = store.load()
                self.assertEqual(len(saved), 2)
                self.assertEqual(saved[0].id, existing.id)
                self.assertEqual((saved[0].status, saved[0].relevant_skills, saved[0].last_result), ("sent", "C#", "receipt"))
                self.assertEqual(saved[0].directory_names, ["ABS CBN Film Productions"])
                self.assertEqual(saved[1].hr_email, "hr@active.test")
                self.assertEqual(saved[1].contact_person, "Another recruiter")
                snapshot = load_active_list(root / ".local" / "active-partners.json")
                self.assertIn(normalize_company(saved[0].directory_names[0]), snapshot.names)
                self.assertIn(normalize_company(saved[1].company_name), snapshot.names)

    def dashboard(self, root):
        code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
            "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
        return AppTest.from_string(code, default_timeout=30)

    def test_review_directory_import_then_save_posting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CompanyStore(root / "companies.json")
            store._write([])
            atomic_text(root / "template.txt", "Hello {company_name}")
            app = self.dashboard(root)
            app.session_state.directory_source_mode = "Upload Excel / CSV"
            matrix = DirectoryTests().matrix()
            # Isolate the upload widget; inject the already decoded source exactly as the loader does.
            def staged_upload(disabled):
                import streamlit as st
                st.session_state.directory_matrix = {"mode": "Upload Excel / CSV", "rows": matrix, "source": SOURCE}
            with patch("sources_ui._uploaded_source", side_effect=staged_upload):
                app.run()
                self.assertFalse(app.exception)
                next(b for b in app.button if b.label == "Clear selection").click().run()
                review_rows_key = next(key for key in app.session_state._state.filtered_state if key.startswith("directory_review_rows_"))
                self.assertTrue(all(not row["include"] for row in app.session_state[review_rows_key]))
                self.assertEqual(store.load(), [])
                editor_key = next(key for key in app.session_state._state.filtered_state
                                  if key.startswith("directory_review_") and not key.startswith(("directory_review_rows_", "directory_review_version_"))
                                  and key.endswith("_1"))
                app.session_state[editor_key] = {"edited_rows": {0: {"contact_person": "Edited contact"}},
                                                 "added_rows": [], "deleted_rows": []}
                next(b for b in app.button if b.label == "Select all valid contacts").click().run()
                selected_rows = app.session_state[review_rows_key]
                self.assertEqual(selected_rows[0]["contact_person"], "Edited contact")
                self.assertTrue(selected_rows[0]["include"])
                self.assertTrue(all(not row["include"] for row in selected_rows if not row["hr_email"]))
                next(b for b in app.button if b.label == "Add reviewed contacts to queue").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(store.load()[0].hr_email, "hr@company.test")
                self.assertEqual(store.load()[0].source_row, 4)
                next(t for t in app.text_input if t.label == "Job posting URL").set_value("https://company.test/jobs/1")
                next(t for t in app.text_area if t.label.startswith("Posting text")).set_value("Backend Intern\nPython and SQL")
                app.run()
                next(b for b in app.button if b.label == "Read posting & suggest details").click().run()
                self.assertFalse(app.exception)
                next(c for c in app.checkbox if c.label.startswith("I checked the source")).check().run()
                next(b for b in app.button if b.label == "Save reviewed posting").click().run()
                self.assertFalse(app.exception)
                saved = store.load()[0]
                self.assertEqual(saved.opportunities[0].title, "Backend Intern")
                self.assertEqual(saved.status, "pending")
                self.assertEqual(saved.relevant_skills, "software development")


class SourcesMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_exposes_only_read_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async with stdio_client(StdioServerParameters(command=sys.executable,
                args=[str(ROOT / "sources_mcp.py")])) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual({tool.name for tool in tools.tools},
                    {"list_directory_worksheets", "read_directory_worksheet"})


if __name__ == "__main__":
    unittest.main()
