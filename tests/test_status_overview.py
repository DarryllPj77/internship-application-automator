from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from core import Company, CompanyStore


class StatusOverviewTests(unittest.TestCase):
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
