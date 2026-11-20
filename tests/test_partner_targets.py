import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core import Company, CompanyStore, exclusive_lock
from partner_matcher import MatcherStore, partner_snapshot
from partner_targets import partner_contacts, add_partner_target

SOURCE = "https://docs.google.com/spreadsheets/d/test/edit?gid=1"


def source_rows():
    return [["", "", "School contact note: school@school.test"],
        ["INDUSTRY PARTNER", "", "TYPE OF INDUSTRY", "COMPANY ADDRESS", "POINT OF CONTACT 1", "", "", "POINT OF CONTACT 2"],
        ["", "", "", "", "Name", "Position", "Email", "Name", "Position", "Email"],
        [1, "Indra Philippines", "Software", "Manila", "First Recruiter", "HR", "first@indra.test", "Second Recruiter", "Manager", "second@indra.test"],
        [2, "Other Company", "Software", "", "Other HR", "HR", "other@other.test"]]


def snapshot():
    return partner_snapshot(source_rows(), source_url=SOURCE, worksheet="GENERAL MASTERLIST")


class PartnerTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = CompanyStore(self.root / "companies.json")
        self.queue._write([])
        self.directory = snapshot()
        self.identity = self.directory["partners"][0]["id"]

    def test_detects_both_pocs_and_does_not_trust_stale_row_numbers(self):
        rows = source_rows()
        rows[3], rows[4] = rows[4], rows[3]
        contacts = partner_contacts(rows, self.directory, self.identity)
        self.assertEqual([c["hr_email"] for c in contacts], ["first@indra.test", "second@indra.test"])
        self.assertEqual([c["source_row"] for c in contacts], [5, 5])
        self.assertEqual(contacts[0]["contact_position"], "HR")
        self.assertEqual(contacts[0]["industry"], "Software")
        self.assertTrue(all(c["valid_email"] for c in contacts))

    def test_missing_and_malformed_emails_are_not_guessed(self):
        rows = source_rows()
        rows[3][6] = "bad@@indra.test"
        rows[3][9] = ""
        contacts = partner_contacts(rows, self.directory, self.identity)
        self.assertEqual([c["hr_email"] for c in contacts], ["bad@@indra.test", ""])
        self.assertFalse(any(c["valid_email"] for c in contacts))
        rows[2] = ["Unrecognized headers"]
        self.assertEqual(partner_contacts(rows, self.directory, self.identity), [])

    def test_adds_pending_target_with_provenance_and_defaults(self):
        contact = partner_contacts(source_rows(), self.directory, self.identity)[1]
        saved, added = add_partner_target(self.queue, self.directory, self.identity, contact, relevant_skills="")
        self.assertTrue(added)
        self.assertEqual(saved.company_name, "Indra Philippines")
        self.assertEqual(saved.hr_email, "second@indra.test")
        self.assertEqual(saved.status, "pending")
        self.assertEqual(saved.relevant_skills, "software development")
        self.assertEqual(saved.source_row, 4)
        self.assertIn("GENERAL MASTERLIST", saved.directory_source)
        self.assertEqual(self.queue.load(), [saved])

    def test_duplicate_preserves_sent_details_and_recovery_state(self):
        existing = Company(company_name="Existing edited name", hr_email="FIRST@indra.test", status="sent",
                           needs_review=True, last_result="gmail-message-id", relevant_skills="SQL")
        self.queue._write([existing])
        contact = partner_contacts(source_rows(), self.directory, self.identity)[0]
        saved, added = add_partner_target(self.queue, self.directory, self.identity, contact, relevant_skills="C#")
        self.assertFalse(added)
        self.assertEqual(saved, existing)
        self.assertEqual(self.queue.load(), [existing])

    def test_invalid_email_unknown_partner_and_batch_lock_do_not_write(self):
        original = self.queue.path.read_bytes()
        with self.assertRaises(ValueError):
            add_partner_target(self.queue, self.directory, self.identity, {"hr_email": "invalid"}, relevant_skills="C#")
        with self.assertRaises(ValueError):
            add_partner_target(self.queue, self.directory, "unknown", {"hr_email": "hr@company.test"}, relevant_skills="C#")
        contact = partner_contacts(source_rows(), self.directory, self.identity)[0]
        with exclusive_lock(self.queue.batch_lock):
            with self.assertRaises(ValueError):
                add_partner_target(self.queue, self.directory, self.identity, contact, relevant_skills="C#")
        self.assertEqual(self.queue.path.read_bytes(), original)


class PartnerTargetUITests(unittest.TestCase):
    def app(self, root):
        code = "from pathlib import Path\nfrom matcher_ui import render_matcher\nrender_matcher(Path(" + repr(str(root)) + "))"
        return AppTest.from_string(code, default_timeout=30)

    def prepare(self, root):
        CompanyStore(root / "companies.json")._write([])
        MatcherStore(root / ".local" / "partner-jobs.json").set_directory(snapshot())

    def test_filter_prepare_choose_poc_and_save_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            with patch("matcher_ui.SheetsReader.read", return_value=source_rows()) as read, \
                 patch("matcher_ui.configured_search_key", return_value=""):
                app = self.app(root).run()
                next(t for t in app.text_input if t.label == "Filter partner names").set_value("Indra").run()
                next(b for b in app.button if b.label == "Add to Target Companies").click().run()
                self.assertFalse(app.exception)
                read.assert_called_once_with(SOURCE, "GENERAL MASTERLIST")
                next(s for s in app.selectbox if s.label == "Recipient / point of contact").select_index(1).run()
                next(t for t in app.text_input if t.label == "Your relevant skills for this company").set_value("C#, ASP.NET Core")
                next(b for b in app.button if b.label == "Save to Target Companies").click().run()
                self.assertFalse(app.exception)
                saved = CompanyStore(root / "companies.json").load()[0]
                self.assertEqual(saved.company_name, "Indra Philippines")
                self.assertEqual(saved.hr_email, "second@indra.test")
                self.assertEqual(saved.relevant_skills, "C#, ASP.NET Core")
                self.assertEqual(saved.status, "pending")
                self.assertEqual(app.session_state["preview_company_id"], saved.id)
                self.assertNotIn("selected_ids", app.session_state)

    def test_cancel_and_failed_source_allow_manual_contact_without_automatic_add(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            with patch("matcher_ui.SheetsReader.read", side_effect=ValueError("not connected")), \
                 patch("matcher_ui.configured_search_key", return_value=""):
                app = self.app(root).run()
                next(b for b in app.button if b.label == "Add to Target Companies").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(CompanyStore(root / "companies.json").load(), [])
                next(b for b in app.button if b.label == "Save to Target Companies").click().run()
                self.assertTrue(app.error)
                self.assertEqual(CompanyStore(root / "companies.json").load(), [])
                next(b for b in app.button if b.label == "Cancel target addition").click().run()
                self.assertFalse(app.exception)
                self.assertFalse(any(t.label == "Target HR email" for t in app.text_input))

    def test_poc_without_email_is_prefilled_and_requires_verified_address(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            rows = source_rows()
            rows[3][6] = rows[3][9] = ""
            with patch("matcher_ui.SheetsReader.read", return_value=rows), \
                 patch("matcher_ui.configured_search_key", return_value=""):
                app = self.app(root).run()
                next(b for b in app.button if b.label == "Add to Target Companies").click().run()
                self.assertEqual(next(t for t in app.text_input if t.label == "Target contact person").value, "First Recruiter")
                next(b for b in app.button if b.label == "Save to Target Companies").click().run()
                self.assertTrue(app.error)
                self.assertEqual(CompanyStore(root / "companies.json").load(), [])
                next(t for t in app.text_input if t.label == "Target HR email").set_value("verified@indra.test")
                next(b for b in app.button if b.label == "Save to Target Companies").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(CompanyStore(root / "companies.json").load()[0].hr_email, "verified@indra.test")


if __name__ == "__main__":
    unittest.main()
