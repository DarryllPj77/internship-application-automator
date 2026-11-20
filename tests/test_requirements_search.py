import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from requirements_search import (SOURCES, RequirementsStore, requirements_query, candidate_url,
    search_candidates, extract_required_section, requirements_document, read_requirements)


def result(**changes):
    return {"title": "Acme Software Developer Intern", "url": "https://www.linkedin.com/jobs/view/developer-intern-123456789/",
        "description": "Requirements: C# and SQL. Azure preferred.", **changes}


class RequirementsTests(unittest.TestCase):
    def test_query_targets_company_role_sources_without_resume_contents(self):
        query = requirements_query("Acme Corp", "software intern", "Philippines", ["LinkedIn", "Indeed"])
        self.assertIn('"Acme"', query)
        self.assertIn("site:linkedin.com", query)
        self.assertIn("site:ph.indeed.com", query)
        self.assertNotIn("C#", query)
        with self.assertRaises(ValueError):
            requirements_query("", "intern", "Philippines", SOURCES)

    def test_specific_board_posts_and_ats_candidates_are_supported_search_pages_are_not(self):
        self.assertEqual(candidate_url(result()["url"]), ("https://www.linkedin.com/jobs/view/123456789/", "LinkedIn"))
        for url in ("https://ph.indeed.com/viewjob?jk=abc123456", "https://ph.jobstreet.com/job/12345",
                    "https://jobs.lever.co/acme/1234", "https://acme.test/careers/software-intern"):
            self.assertIsNotNone(candidate_url(url))
        for url in ("https://www.linkedin.com/jobs/search/?keywords=acme", "https://ph.jobstreet.com/jobs?keywords=acme",
                    "https://www.linkedin.com.evil.test/jobs/search/", "https://127.0.0.1/careers/job",
                    "https://localhost/jobs/intern", "file:///jobs/intern"):
            self.assertIsNone(candidate_url(url))

    def test_candidates_include_non_csharp_roles_and_preserve_excerpt_quality(self):
        results = [result(), result(url="https://www.linkedin.com/jobs/view/123456789/?tracking=1"),
                   result(url="https://ph.jobstreet.com/job/999999", title="Java Intern", description="Java and Spring Boot required")]
        found = search_candidates("Acme Corp", results, SOURCES)
        self.assertEqual(len(found), 2)
        self.assertIn("Java", found[1]["excerpt"])
        self.assertNotIn("requirements", found[0])
        self.assertEqual(search_candidates("Acme", results, ["Indeed"]), [])

    def test_requirements_section_excludes_duties_and_optional_block(self):
        text = "About us\nA company\nRequired skills:\nC#\nSQL\nNice to have:\nAzure\nResponsibilities:\nWrite code\nBenefits:\nAllowance"
        self.assertEqual(extract_required_section(text), "C#\nSQL")
        self.assertEqual(extract_required_section("Required skills: Python\nGit\nBenefits: Meals"), "Python\nGit")
        self.assertEqual(extract_required_section("We use C# for some projects"), "")
        self.assertEqual(extract_required_section("- Required skills:\n- C#\n- Nice to have:\n- Azure"), "- C#")

    def test_structured_qualifications_and_organization_name(self):
        job = {"@type": "JobPosting", "title": "Backend Intern", "hiringOrganization": {"name": "Acme", "description": "A long organization description"},
               "qualifications": "<ul><li>C#</li><li>SQL</li></ul>", "datePosted": "2026-11-20"}
        html = '<script type="application/ld+json">' + json.dumps(job) + '</script><footer>Python</footer>'
        document = requirements_document(html, "https://acme.test/jobs/1")
        self.assertEqual(document["employer"], "Acme")
        self.assertEqual(document["evidence_type"], "structured_qualifications")
        self.assertIn("C#", document["text"])
        self.assertNotIn("Python", document["text"])
        with self.assertRaises(ValueError):
            requirements_document('<script type="application/ld+json">' + json.dumps([job, job]) + '</script>', "https://acme.test/jobs/1")

    def test_full_fetch_is_not_attempted_for_job_board_account_pages(self):
        with patch("requirements_search.fetch_public_posting") as fetch:
            for source in ("LinkedIn", "JobStreet", "Indeed"):
                with self.assertRaises(ValueError):
                    read_requirements({"source": source, "url": result()["url"]})
            fetch.assert_not_called()
            fetch.return_value = ("<h1>Intern</h1><h2>Requirements</h2><p>C#</p><h2>Benefits</h2><p>Meals</p>", "https://acme.test/jobs/1")
            document = read_requirements({"source": "Company career pages", "url": "https://acme.test/jobs/1"})
            self.assertEqual(document["text"], "C#")
            fetch.assert_called_once_with("https://acme.test/jobs/1", blocked_domains=("indeed.com",))

    def test_evidence_store_requires_company_confirmation_and_keeps_source_kind(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RequirementsStore(Path(temporary) / ".local" / "requirements.json")
            candidate = search_candidates("Acme", [result()], SOURCES)[0]
            with self.assertRaises(ValueError):
                store.apply("Acme", candidate, "C#", "search_excerpt", employer_confirmed=False)
            with self.assertRaises(ValueError):
                store.apply("Other Company", candidate, "C#", "search_excerpt", employer_confirmed=True)
            record = store.apply("Acme", candidate, "C#", "search_excerpt", employer_confirmed=True)
            self.assertEqual(record["evidence_type"], "search_excerpt")
            self.assertEqual(store.load()["applied"]["acme"]["url"], candidate["url"])


class RequirementsUITests(unittest.TestCase):
    def finder(self, root):
        code = "from pathlib import Path\nimport streamlit as st\nfrom requirements_ui import requirements_finder\n"
        code += "record=requirements_finder(Path(" + repr(str(root)) + "),'test','Acme')\n"
        code += "if record: st.session_state.applied_record=record"
        return AppTest.from_string(code, default_timeout=30)

    def test_missing_key_is_visible_and_search_is_disabled(self):
        with tempfile.TemporaryDirectory() as temporary, patch("requirements_ui.configured_search_key", return_value=""):
            app = self.finder(Path(temporary)).run()
            self.assertFalse(app.exception)
            self.assertTrue(next(b for b in app.button if b.label == "Search company job requirements").disabled)

    def test_board_excerpt_can_only_be_used_after_explicit_review(self):
        with tempfile.TemporaryDirectory() as temporary, patch("requirements_ui.configured_search_key", return_value="test"), \
             patch("requirements_ui.BraveSearch.search", return_value=[result()]), patch("requirements_ui.read_requirements") as full:
            app = self.finder(Path(temporary)).run()
            next(b for b in app.button if b.label == "Search company job requirements").click().run()
            self.assertFalse(app.exception)
            full.assert_not_called()
            self.assertTrue(next(b for b in app.button if b.label == "Use reviewed requirements").disabled)
            next(c for c in app.checkbox if c.label.startswith("I confirmed this posting")).check().run()
            next(b for b in app.button if b.label == "Use reviewed requirements").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["applied_record"]["evidence_type"], "search_excerpt")

    def test_applying_source_matches_resume_subset_and_retains_manual_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cv = root / "resume.pdf"
            cv.write_bytes(b"%PDF-1.4 test fixture")
            code = "from pathlib import Path\nimport streamlit as st\nfrom skills_ui import relevant_skills_picker\ncompany=st.text_input('Company name',value='Acme')\nrelevant_skills_picker(Path(" + repr(str(root)) + "),'test',company_name=company)"
            with patch("requirements_ui.configured_search_key", return_value="test"), \
                 patch("requirements_ui.BraveSearch.search", return_value=[result(description="Required skills: C#, SQL\nNice to have: Azure")]), \
                 patch("skills_ui._read_skills", return_value=["C#", "SQL", "Azure", "Python"]):
                app = AppTest.from_string(code, default_timeout=30)
                app.session_state.cv_path = str(cv)
                app.run()
                next(b for b in app.button if b.label == "Search company job requirements").click().run()
                next(c for c in app.checkbox if c.label.startswith("I confirmed this posting")).check().run()
                next(b for b in app.button if b.label == "Use reviewed requirements").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(next(m for m in app.multiselect if m.label.startswith("Resume skills")).value, ["C#", "SQL"])
                field = next(t for t in app.text_input if t.label == "Relevant skills")
                self.assertEqual(field.value, "C#, SQL")
                field.set_value("C# and SQL development").run()
                self.assertEqual(next(t for t in app.text_input if t.label == "Relevant skills").value, "C# and SQL development")
                next(t for t in app.text_input if t.label == "Company name").set_value("Another Company").run()
                self.assertFalse(app.exception)
                self.assertEqual(next(t for t in app.text_input if t.label == "Relevant skills").value, "")
                self.assertEqual(next(t for t in app.text_area if t.label == "Required skills / job requirements").value, "")

    def test_matcher_search_handoff_populates_only_reviewed_resume_skills_in_target(self):
        from core import CompanyStore
        from partner_matcher import MatcherStore, partner_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cv = root / "resume.pdf"
            cv.write_bytes(b"%PDF-1.4 fixture")
            CompanyStore(root / "companies.json")._write([])
            rows = [["Company", "Name", "Position", "Email"], ["Acme", "Recruiter", "HR", "hr@acme.test"]]
            MatcherStore(root / ".local" / "partner-jobs.json").set_directory(partner_snapshot(rows,
                source_url="https://docs.google.com/spreadsheets/d/test/edit", worksheet="Partners", first_data_row=2, company_column=0))
            code = "from pathlib import Path\nfrom matcher_ui import render_matcher\nrender_matcher(Path(" + repr(str(root)) + "))"
            with patch("requirements_ui.configured_search_key", return_value="test"), \
                 patch("matcher_ui.configured_search_key", return_value=""), \
                 patch("requirements_ui.BraveSearch.search", return_value=[result(description="Required skills: C#, SQL")]), \
                 patch("matcher_ui.SheetsReader.read", return_value=rows), \
                 patch("skills_ui._read_skills", return_value=["C#", "SQL", "Azure"]):
                app = AppTest.from_string(code, default_timeout=30)
                app.session_state.cv_path = str(cv)
                app.run()
                next(b for b in app.button if b.label == "Search company job requirements").click().run()
                next(c for c in app.checkbox if c.label.startswith("I confirmed this posting")).check().run()
                next(b for b in app.button if b.label == "Use reviewed requirements").click().run()
                next(b for b in app.button if b.label == "Add to Target Companies").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(next(t for t in app.text_input if t.label == "Your relevant skills for this company").value, "C#, SQL")
                next(b for b in app.button if b.label == "Save to Target Companies").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(CompanyStore(root / "companies.json").load()[0].relevant_skills, "C#, SQL")


if __name__ == "__main__":
    unittest.main()
