from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from active_partners import build_active_list, load_active_list, save_active_list
from core import Company
from partner_matcher import normalize_company
from ui import company_table

URL = "https://docs.google.com/spreadsheets/d/test-sheet/edit"


class ActivePartnerTests(unittest.TestCase):
    def test_mapping_normalization_and_snapshot_persistence(self):
        rows = [["title"], [], ["", "Company"], [1, "Acme Inc. *"], [2, "ACME Corporation"], [3, "Other Ltd."]]
        snapshot = build_active_list(rows, source_url=URL, worksheet="Active TECH")
        self.assertEqual(snapshot.names, {"acme", "other"})
        self.assertNotIn(normalize_company("Acme Services"), snapshot.names)
        self.assertEqual(len(snapshot.company_names), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".local" / "active.json"
            self.assertIsNone(load_active_list(path))
            save_active_list(path, snapshot)
            self.assertEqual(load_active_list(path), snapshot)
            self.assertEqual(load_active_list(path).worksheet, "Active TECH")

    def test_empty_mapping_is_rejected_without_overwriting_previous_list(self):
        with self.assertRaises(ValueError):
            build_active_list([[]], source_url=URL, worksheet="Active")
        with self.assertRaises(ValueError):
            build_active_list([["Acme"]], source_url=URL, worksheet="Active", first_data_row=0)

    def test_membership_is_transient_and_keeps_sent_status_and_company_data(self):
        companies = [Company(company_name="Acme Inc.", hr_email="a@acme.com", status="sent", directory_names=["ACME Active Name"]),
                     Company(company_name="Acme Services", hr_email="b@acme.com")]
        original = [company.model_dump() for company in companies]
        with patch("ui._company_table", return_value=None) as component:
            company_table(companies, [], active_names={"acme"})
            args = component.call_args.kwargs
            self.assertEqual([r["active_partner"] for r in args["rows"]], [True, False])
            company_table(companies, [], active_names={"acme active name"})
            self.assertEqual([r["active_partner"] for r in component.call_args.kwargs["rows"]], [True, False])
            self.assertTrue(args["active_available"])
            self.assertEqual(args["rows"][0]["status"], "sent")
        self.assertEqual([company.model_dump() for company in companies], original)

    def test_ui_requires_review_and_reuses_saved_list_without_network_on_reruns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(f"SHEETS_URL={URL}\n", encoding="utf-8")
            script = ("from pathlib import Path\nfrom active_partners_ui import render_active_partner_source\n"
                      f"render_active_partner_source(Path({str(root)!r}), [])")
            with patch("active_partners_ui.os.getenv", return_value=None), patch("active_partners_ui.SheetsReader") as reader:
                reader.return_value.worksheets.return_value = [{"title": "GENERAL MASTERLIST"}, {"title": "Active TECH"}]
                reader.return_value.read.return_value = [["title"], [], ["", "Company"], [1, "Acme Inc."]]
                app = AppTest.from_string(script, default_timeout=30).run()
                next(b for b in app.button if b.label == "List active-list worksheets").click().run()
                next(s for s in app.selectbox if s.label == "Active partner worksheet").select("Active TECH").run()
                next(b for b in app.button if b.label == "Read active worksheet").click().run()
                save = next(b for b in app.button if b.label == "Use worksheet as active partner list")
                self.assertTrue(save.disabled)
                app.checkbox[0].check().run()
                next(b for b in app.button if b.label == "Use worksheet as active partner list").click().run()
                self.assertFalse(app.exception)
                snapshot = load_active_list(root / ".local" / "active-partners.json")
                self.assertEqual(snapshot.names, {"acme"})
                app.run()
                self.assertEqual(reader.return_value.read.call_count, 1)
                self.assertEqual(reader.return_value.worksheets.call_count, 1)
