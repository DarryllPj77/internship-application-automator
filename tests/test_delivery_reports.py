import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from streamlit.testing.v1 import AppTest

from core import Company, CompanyStore
from delivery_reports import load_monitor, parse_notice, scan_delivery_reports, utcnow
from sent_checker import apply_sent_checks


def notice(*, action="failed", reason="Address not found; 550 5.1.1 account does not exist", recipient="hr@acme.com", thread="thread1", sender="mailer-daemon@googlemail.com", date=None):
    date = date or utcnow()
    return (f"Thread ID: {thread}\nSubject: Delivery Status Notification ({'Delay' if action == 'delayed' else 'Failure'})\n"
            f"From: Mail Delivery Subsystem <{sender}>\nTo: sender@gmail.com\nDate: {format_datetime(date)}\n\n"
            f"{reason}\nFinal-Recipient: rfc822; {recipient}\nAction: {action}\nStatus: {'4.7.1' if action == 'delayed' else '5.1.1'}\n")


class DeliveryReportTests(unittest.TestCase):
    def test_delayed_action_wins_over_quoted_550_error(self):
        event = parse_notice("a123", notice(action="delayed", reason="550 The server could not deliver mail. Gmail will retry."))
        self.assertEqual(event["kind"], "delayed")
        self.assertIn("No final failure", event["reason"])

    def test_recognizes_short_reasons_and_rejects_human_mail(self):
        for reason, expected in (("Recipient inbox full", "inbox is full"),
                ("The recipient server did not accept requests to connect: timed out", "could not be reached"),
                ("Message blocked; 550 5.4.1 access denied", "blocked or rejected")):
            text = notice(reason=reason).replace("Status: 5.1.1", "Status: 5.7.0")
            self.assertIn(expected, parse_notice("a123", text)["reason"])
        self.assertIsNone(parse_notice("a123", notice(sender="friend@gmail.com")))
        self.assertIsNone(parse_notice("a123", notice() + "Final-Recipient: rfc822; other@other.com\n"))

    def scan(self, texts, *, status="sent", latest_after=False, wrong_thread=False, last_operation_at=""):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        store = CompanyStore(root / "companies.json")
        company = Company(company_name="Acme", hr_email="hr@acme.com", status=status, last_operation_at=last_operation_at)
        store._write([company])
        async def read_tool(name, args):
            if name == "search_emails":
                return "\n\n".join("ID: " + identity for identity in texts)
            self.assertEqual(name, "read_email")
            return texts[args["messageId"]]
        connection = SimpleNamespace(read_tool=AsyncMock(side_effect=read_tool), find_sent=AsyncMock(return_value=[{
            "message_id": "sent123", "thread_id": "different" if wrong_thread else "thread1",
            "date": format_datetime(utcnow() + timedelta(days=1) if latest_after else utcnow() - timedelta(hours=1))}]))
        @asynccontextmanager
        async def connect():
            yield connection
        client = SimpleNamespace(connect=connect)
        state = root / ".local" / "delivery-monitor.json"
        result = asyncio.run(scan_delivery_reports(store, client, state, force=True))
        return store, client, state, result

    def test_correlated_failure_updates_status_reason_and_is_idempotent(self):
        store, client, path, result = self.scan({"a123": notice()})
        saved = store.load()[0]
        self.assertEqual(saved.status, "failed")
        self.assertEqual(saved.status_reason, "Recipient email address was not found.")
        self.assertEqual(saved.delivery_outbound_id, "sent123")
        self.assertEqual(result["updated"], 1)
        self.assertEqual(asyncio.run(scan_delivery_reports(store, client, path, force=True))["updated"], 0)

    def test_delay_is_not_a_failure_or_an_automatic_resend(self):
        store, _, _, _ = self.scan({"a123": notice(action="delayed")}, status="drafted")
        self.assertEqual(store.load()[0].status, "sent")
        self.assertEqual(store.load()[0].delivery_state, "delayed")

    def test_newer_send_or_different_thread_is_not_marked_failed(self):
        for options in ({"latest_after": True}, {"wrong_thread": True},
                        {"last_operation_at": utcnow().isoformat(), "status": "drafted"}):
            store, _, _, result = self.scan({"a123": notice()}, **options)
            self.assertEqual(result["updated"], 0)
            self.assertEqual(store.load()[0].delivery_state, "unknown")

    def test_final_failure_takes_priority_over_delay(self):
        store, _, _, _ = self.scan({"a123": notice(action="delayed"), "b123": notice()})
        self.assertEqual(store.load()[0].delivery_state, "failed")

    def test_manual_review_can_save_failed_with_reason_but_requires_one(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CompanyStore(Path(directory) / "companies.json")
            company = Company(company_name="Acme", hr_email="hr@acme.com", status="drafted")
            store._write([company])
            report = [{"company": company.model_dump(), "matches": []}]
            with self.assertRaises(ValueError):
                apply_sent_checks(store, report, [company.id], outcome="failed")
            apply_sent_checks(store, report, [company.id], outcome="failed", reason="Recipient inbox is full.")
            self.assertEqual(store.load()[0].status, "failed")
            self.assertEqual(store.load()[0].status_reason, "Recipient inbox is full.")

    def test_review_panel_saves_failed_outcome_and_short_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(company_name="Acme", hr_email="hr@acme.com", status="sent")
            store = CompanyStore(root / "companies.json")
            store._write([company])
            (root / "template.txt").write_text("Hello {company_name}", encoding="utf-8")
            source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
            source = source.replace("ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(source, default_timeout=30)
            app.session_state["sent_check_report"] = [{"company": company.model_dump(),
                "matches": [{"message_id": "a123", "date": "25 Nov 2026"}]}]
            app.run()
            next(item for item in app.selectbox if item.label == "Company status to review").select("Sent").run()
            next(item for item in app.selectbox if item.label == "Reviewed outcome").select("Failed").run()
            next(item for item in app.multiselect if item.label == "Reviewed companies to update").set_value([company.id]).run()
            self.assertTrue(next(item for item in app.button if item.label.startswith("Mark reviewed companies Failed")).disabled)
            next(item for item in app.selectbox if item.label == "Failure reason").select("Recipient inbox full").run()
            next(item for item in app.button if item.label.startswith("Mark reviewed companies Failed")).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(store.load()[0].status, "failed")
            self.assertEqual(store.load()[0].status_reason, "Recipient inbox is full.")

    def test_review_defaults_to_drafted_and_filters_cached_processed_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            companies = [Company(company_name=status.title(), hr_email=f"{status}@example.com", status=status)
                         for status in ("drafted", "sent", "failed", "pending")]
            store = CompanyStore(root / "companies.json")
            store._write(companies)
            (root / "template.txt").write_text("Hello {company_name}", encoding="utf-8")
            source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
            source = source.replace("ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(source, default_timeout=30)
            app.session_state["sent_check_companies"] = [c.id for c in companies[:3]]
            app.session_state["sent_check_report"] = [{"company": c.model_dump(),
                "matches": [{"message_id": f"abc{i}", "date": "25 Nov 2026"}]}
                for i, c in enumerate(companies[:3])]
            app.run()
            picker = lambda: next(item for item in app.multiselect if item.label == "Companies to review (up to 25)")
            links = lambda: [item.label for item in app.get("link_button") if item.label.startswith("Review sent message")]
            self.assertEqual(picker().value, [companies[0].id])
            self.assertEqual(len(picker().options), 1)
            self.assertEqual(len(links()), 1)
            status = lambda: next(item for item in app.selectbox if item.label == "Company status to review")
            for index in (1, 2):
                status().select(companies[index].status.title()).run()
                self.assertEqual(len(picker().options), 1)
                self.assertEqual(len(links()), 1)
                self.assertIn(companies[index].company_name, links()[0])
                self.assertEqual(picker().value, [])
                picker().set_value([companies[index].id]).run()
            status().select("Drafted").run()
            self.assertEqual(picker().value, [])
            self.assertEqual(len(links()), 1)
            # A subsequent queue update must also hide an old Drafted report.
            companies[0].status = "sent"
            store._write(companies)
            app.run()
            self.assertEqual(picker().value, [])
            self.assertEqual(links(), [])
            self.assertFalse(app.exception)
            self.assertEqual([c.status for c in store.load()], ["sent", "sent", "failed", "pending"])
