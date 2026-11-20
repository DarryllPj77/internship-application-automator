import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core import CompanyStore, atomic_text
from resume_skills import detect_skills, pdf_skills, match_required_skills, resume_skill_text

ROOT = Path(__file__).resolve().parents[1]


def resume_pdf(text):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(("BT /F1 12 Tf 40 750 Td (" + escaped + ") Tj ET").encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class ResumeSkillTests(unittest.TestCase):
    def test_prefers_declared_skill_section_and_excludes_current_learning(self):
        text = "Summary: I express interest in React.\nTECHNICAL SKILLS\nLanguages: C#, C, Python\nCurrently Learning: Azure\nDocker\nTools: Git\nPROJECTS\nReact and Vue project"
        skills = detect_skills(resume_skill_text(text))
        self.assertEqual(skills, ["C#", "C", "Python", "Git"])
    def test_pdf_extracts_known_resume_skills_without_inferring_other_languages(self):
        skills = pdf_skills(resume_pdf("C# ASP.NET Core PostgreSQL JavaScript"))
        self.assertIn("C#", skills)
        self.assertIn("ASP.NET Core", skills)
        self.assertIn("PostgreSQL", skills)
        self.assertNotIn("Java", skills)
        self.assertNotIn("ASP.NET", skills)
        self.assertEqual(detect_skills("https://python.net me@react.test"), [])

    def test_required_matches_intersect_resume_and_exclude_optional_sections(self):
        available = ["C#", "SQL", "Azure", "React", "Python"]
        text = "Required: C#, SQL\nNice-to-have: Azure\nReact\nRequired qualifications:\nPython\nDocker"
        self.assertEqual(match_required_skills(available, text), ["C#", "SQL", "Python"])
        self.assertEqual(match_required_skills(available, "Angular and Rust"), [])
        self.assertEqual(match_required_skills(available, "Indra Philippines"), [])
        self.assertEqual(match_required_skills(available, "C#, Azure (preferred)"), [])
        self.assertEqual(match_required_skills(available, "C# required, Azure optional"), ["C#"])
        self.assertEqual(match_required_skills(available, "C# not required"), [])

    def test_unreadable_and_scanned_pdf_provide_manual_fallback_errors(self):
        with self.assertRaises(ValueError):
            pdf_skills(b"not a PDF")
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        data = io.BytesIO()
        writer.write(data)
        with self.assertRaisesRegex(ValueError, "No readable CV text"):
            pdf_skills(data.getvalue())


class ResumeSkillUITests(unittest.TestCase):
    def prepare(self, root):
        folder = root / "uploads" / "cvs" / "test"
        folder.mkdir(parents=True)
        (folder / "resume.pdf").write_bytes(resume_pdf("C# PostgreSQL Azure Python"))

    def picker(self, root):
        app = AppTest.from_string("from pathlib import Path\nfrom skills_ui import relevant_skills_picker\n"
            "relevant_skills_picker(Path(" + repr(str(root)) + "), 'test_skills')", default_timeout=30)
        app.session_state.cv_path = str(root / "uploads" / "cvs" / "test" / "resume.pdf")
        return app

    def test_empty_by_default_subset_updates_text_and_manual_edits_persist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            app = self.picker(root).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.multiselect[0].value, [])
            self.assertEqual(app.text_input[0].value, "")
            app.multiselect[0].set_value(["C#", "PostgreSQL"]).run()
            self.assertEqual(app.text_input[0].value, "C#, PostgreSQL")
            app.text_input[0].set_value("C# and PostgreSQL database development").run()
            app.text_area[0].set_value("C# required").run()
            self.assertEqual(app.text_input[0].value, "C# and PostgreSQL database development")

    def test_match_button_selects_only_existing_required_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            app = self.picker(root).run()
            app.text_area[0].set_value("Required: C#, PostgreSQL, Angular\nNice to have:\nAzure")
            next(b for b in app.button if b.label == "Select matching resume skills").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.multiselect[0].value, ["C#", "PostgreSQL"])
            self.assertEqual(app.text_input[0].value, "C#, PostgreSQL")

    def test_missing_resume_still_allows_editable_manual_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.picker(Path(temporary)).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.multiselect[0].disabled)
            app.text_input[0].set_value("C# and SQL").run()
            self.assertEqual(app.text_input[0].value, "C# and SQL")

    def test_add_company_keeps_entered_contact_fields_when_skills_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            CompanyStore(root / "companies.json")._write([])
            atomic_text(root / "template.txt", "Hello {company_name}: {relevant_skills}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(code, default_timeout=30)
            app.session_state.cv_path = str(root / "uploads" / "cvs" / "test" / "resume.pdf")
            app.run()
            next(t for t in app.text_input if t.label == "Company name").set_value("Test Company")
            next(t for t in app.text_input if t.label == "HR email").set_value("hr@company.test")
            app.run()
            next(m for m in app.multiselect if m.key == "new_company_skills_selected").set_value(["C#"]).run()
            self.assertEqual(next(t for t in app.text_input if t.label == "Company name").value, "Test Company")
            self.assertEqual(next(t for t in app.text_input if t.label == "HR email").value, "hr@company.test")
            next(t for t in app.text_input if t.label == "Relevant skills").set_value("C# software development")
            next(b for b in app.button if b.label == "Add Company").click().run()
            self.assertFalse(app.exception)
            saved = CompanyStore(root / "companies.json").load()[0]
            self.assertEqual(saved.relevant_skills, "C# software development")
            self.assertEqual(saved.hr_email, "hr@company.test")
            self.assertEqual(next(t for t in app.text_input if t.label == "Company name").value, "")

    def test_matcher_target_recipient_survives_resume_skill_selection(self):
        from partner_matcher import MatcherStore, partner_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            CompanyStore(root / "companies.json")._write([])
            rows = [["Company", "Name", "Position", "Email"], ["Company", "Recruiter", "HR", "hr@company.test"]]
            snapshot = partner_snapshot(rows, source_url="https://docs.google.com/spreadsheets/d/test/edit", worksheet="Partners", first_data_row=2, company_column=0)
            MatcherStore(root / ".local" / "partner-jobs.json").set_directory(snapshot)
            code = "from pathlib import Path\nfrom matcher_ui import render_matcher\nrender_matcher(Path(" + repr(str(root)) + "))"
            with patch("matcher_ui.SheetsReader.read", return_value=rows), patch("matcher_ui.configured_search_key", return_value=""):
                app = AppTest.from_string(code, default_timeout=30)
                app.session_state.cv_path = str(root / "uploads" / "cvs" / "test" / "resume.pdf")
                app.run()
                next(b for b in app.button if b.label == "Add to Target Companies").click().run()
                next(t for t in app.text_input if t.label == "Target HR email").set_value("edited@company.test").run()
                picker = next(m for m in app.multiselect if m.label == "Resume skills (choose only relevant ones)")
                picker.set_value(["C#"]).run()
                self.assertEqual(next(t for t in app.text_input if t.label == "Target HR email").value, "edited@company.test")
                next(b for b in app.button if b.label == "Save to Target Companies").click().run()
                self.assertFalse(app.exception)
                saved = CompanyStore(root / "companies.json").load()[0]
                self.assertEqual(saved.hr_email, "edited@company.test")
                self.assertEqual(saved.relevant_skills, "C#")


if __name__ == "__main__":
    unittest.main()
