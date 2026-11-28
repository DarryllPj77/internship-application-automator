from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from core import Company, CompanyStore


class StatusOverviewTests(unittest.TestCase):
    def test_failure_description_filter_selects_only_visible_reviewed_contacts_for_drafts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "companies.json"
            store = CompanyStore(path)
            reason = "Gmail sending limit reached; message was not sent."
            first = Company(company_name="Limit", hr_email="limit@example.com", status="failed", status_reason=reason)
            unresolved = Company(company_name="Needs review", hr_email="review@example.com", status="failed",
                                 status_reason=reason, needs_review=True)
            other = Company(company_name="Other reason", hr_email="other@example.com", status="failed", status_reason="Inbox full")
            sent = Company(company_name="Sent", hr_email="sent@example.com", status="sent", status_reason=reason)
            store._write([first, unresolved, other, sent])
            original = path.read_bytes()
            source = ("from pathlib import Path\nfrom core import CompanyStore\n"
                      "from status_overview_ui import show_status_overview\n"
                      f"show_status_overview(CompanyStore(Path({str(path)!r})))")
            app = AppTest.from_string(source, default_timeout=30).run()
            app.selectbox[0].select("Failed").run()
            next(s for s in app.selectbox if s.label == "Failure description").select(reason).run()
            self.assertEqual(app.dataframe[0].value["Company"].tolist(), ["Limit", "Needs review"])
            next(b for b in app.button if b.label == "Select all filtered").click().run()
            self.assertEqual(app.dataframe[0].value["Select"].tolist(), [True, False])
            self.assertEqual(app.dataframe[0].value["#"].tolist(), [1, 2])
            next(b for b in app.button if b.label == "Clear selection").click().run()
            self.assertEqual(app.dataframe[0].value["Select"].tolist(), [False, False])
            self.assertTrue(next(b for b in app.button if b.key == "overview_prepare_failed").disabled)
            next(b for b in app.button if b.label == "Select all filtered").click().run()
            next(b for b in app.button if b.key == "overview_prepare_failed").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.failed_redraft_request, [first.id])
            self.assertEqual(app.session_state.next_workspace_section, "batch")
            self.assertEqual(path.read_bytes(), original)
            # Once a reason group leaves Failed, the next overview must not keep an invalid filter.
            store._write([other, sent])
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(next(s for s in app.selectbox if s.label == "Failure description").value, "All failure descriptions")
            self.assertEqual(app.dataframe[0].value["Company"].tolist(), ["Other reason"])

    def test_button_opens_four_statuses_with_numbering_reasons_and_no_mutations(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "companies.json"
            store = CompanyStore(path)
            companies = [Company(company_name=status.title(), hr_email=f"{status}@example.com", status=status)
                         for status in ("pending", "drafted", "sent", "failed")]
            companies[-1].status_reason = "Recipient inbox is full."
            companies.append(Company(company_name="Other failure", hr_email="other@example.com", status="failed"))
            store._write(companies)
            original = path.read_bytes()
            app = AppTest.from_string(
                "from pathlib import Path\nimport streamlit as st\nfrom core import CompanyStore\n"
                "from status_overview_ui import show_status_overview\n"
                "if st.button('View companies by status'): st.session_state.opened = True\n"
                f"if st.session_state.get('opened'): show_status_overview(CompanyStore(Path({str(path)!r})))"
            ).run()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox[0].options, ["Pending", "Drafted", "Sent", "Failed"])
            for status in ("Pending", "Drafted", "Sent", "Failed"):
                app.selectbox[0].select(status).run()
                table = app.dataframe[0].value
                self.assertEqual(table["#"].tolist(), list(range(1, len(table) + 1)))
                self.assertEqual(table.iloc[0]["Company"], status)
                if status == "Failed":
                    self.assertEqual(table.iloc[0]["Failure reason"], "Recipient inbox is full.")
                    self.assertIn("No reason recorded", table.iloc[1]["Failure reason"])
                self.assertEqual(path.read_bytes(), original)
            store._write([])
            app.selectbox[0].select("Pending").run()
            self.assertFalse(app.exception)
            self.assertFalse(app.dataframe)
            self.assertIn("No companies", app.info[0].value)
