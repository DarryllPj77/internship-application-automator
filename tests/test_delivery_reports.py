import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from core import Company, CompanyStore, SUBJECT
from delivery_reports import load_monitor, parse_notice, scan_delivery_reports, utcnow
from sent_checker import apply_sent_checks


def notice(*, action="failed", reason="Address not found; 550 5.1.1 account does not exist", recipient="hr@acme.com", thread="thread1", sender="mailer-daemon@googlemail.com", date=None):
    date = date or utcnow()
    return (f"Thread ID: {thread}\nSubject: Delivery Status Notification ({'Delay' if action == 'delayed' else 'Failure'})\n"
            f"From: Mail Delivery Subsystem <{sender}>\nTo: sender@gmail.com\nDate: {format_datetime(date)}\n\n"
            f"{reason}\nFinal-Recipient: rfc822; {recipient}\nAction: {action}\nStatus: {'4.7.1' if action == 'delayed' else '5.1.1'}\n")


class DeliveryReportTests(unittest.TestCase):
    def test_selected_check_finds_limit_failure_beyond_newest_fifty_mailbox_notices(self):
        from sent_checker import check_with_delivery
        import re
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            company = Company(company_name="Selected", hr_email="hr@acme.com", status="sent")
            store._write([company])
            sent_at = utcnow() - timedelta(minutes=3)
            notices = {f"{i:04x}": sent_at + timedelta(seconds=i + 1) for i in range(51)}
            target = "0000"  # Hidden by the newest fifty in the initial search.
            async def read_tool(name, arguments):
                if name == "search_emails":
                    query = arguments["query"]
                    self.assertNotIn("newer_than:30d", query)
                    after = int(re.search(r"after:(\d+)", query)[1])
                    before = int(re.search(r"before:(\d+)", query)[1])
                    ids = [key for key in reversed(notices) if after < notices[key].timestamp() < before]
                    return "\n".join("ID: " + key for key in ids[:arguments["maxResults"]])
                identity = arguments["messageId"]
                if identity == target:
                    return (f"Thread ID: thread1\nSubject: Re: {SUBJECT}\nFrom: mailer-daemon@googlemail.com\n"
                            f"Date: {format_datetime(notices[identity])}\n\nYou have reached a limit for sending mail. Your message was not sent.")
                return notice(date=notices[identity], recipient="unrelated@example.com")
            connection = SimpleNamespace(read_tool=AsyncMock(side_effect=read_tool), find_sent=AsyncMock(return_value=[{
                "message_id": "sent123", "thread_id": "thread1", "date": format_datetime(sent_at)}]))
            @asynccontextmanager
            async def connect():
                yield connection
            report, result = asyncio.run(check_with_delivery(store, SimpleNamespace(connect=connect), [company],
                sent_at.date(), root / "monitor.json"))
            self.assertFalse(result["truncated"])
            self.assertEqual(result["inspected"], 51)
            self.assertEqual(store.load()[0].status, "failed")
            self.assertIn("Gmail sending limit reached", report[0]["company"]["status_reason"])
            searches = [call for call in connection.read_tool.call_args_list if call.args[0] == "search_emails"]
            self.assertGreater(len(searches), 1)

    def test_latest_check_hides_previous_failures_but_history_and_queue_keep_their_reasons(self):
        from delivery_reports import update_monitor
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            store._write([Company(company_name="Recorded failure", hr_email="hr@example.com", status="failed",
                                  status_reason="Recipient inbox is full.")])
            original = store.path.read_bytes()
            path = root / ".local" / "delivery-monitor.json"
            event = {"company_name": "Recorded failure", "recipient": "hr@example.com", "kind": "failed",
                     "reason": "Recipient inbox is full.", "notice_id": "a123", "notice_at": utcnow().isoformat()}
            update_monitor(path, events=[event], latest_events=[event], seen=["a123"])
            async def scan(*args, **kwargs):
                update_monitor(path, latest_events=[], last_checked_at=utcnow().isoformat())
                return {"updated": 0, "inspected": 0, "events": []}
            source = ("import asyncio\nfrom pathlib import Path\nfrom core import CompanyStore\n"
                      "from delivery_monitor_ui import render_delivery_monitor\n"
                      f"root = Path({str(root)!r})\n"
                      "render_delivery_monitor(root, CompanyStore(root / 'companies.json'), asyncio.run)")
            with patch("delivery_monitor_ui.scan_delivery_reports", side_effect=scan):
                app = AppTest.from_string(source, default_timeout=30).run()
                self.assertEqual(len(app.dataframe), 1)
                next(b for b in app.button if b.label == "Check delivery problems now").click().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.dataframe)
                self.assertTrue(any("No new delivery outcomes" in item.value for item in app.info))
                view = lambda: next(s for s in app.selectbox if s.label == "Delivery results")
                view().select("Saved delivery history").run()
                self.assertEqual(app.dataframe[0].value.iloc[0]["Short reason"], "Recipient inbox is full.")
                self.assertEqual(app.dataframe[0].value.iloc[0]["#"], 1)
                next(b for b in app.button if b.label == "Check delivery problems now").click().run()
                self.assertEqual(view().value, "Latest check — new outcomes")
                self.assertFalse(app.dataframe)
                self.assertEqual(store.path.read_bytes(), original)
                self.assertEqual(load_monitor(path)["events"], [event])

    def test_gmail_sending_limit_reply_is_a_sender_failure_not_a_bad_address(self):
        text = (f"Thread ID: thread1\nSubject: Re: {SUBJECT}\n"
                f"From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\nDate: {format_datetime(utcnow())}\n\n"
                "You have reached a limit for sending mail. Your message was not sent.\r\r\n"
                "Quoted original application text.")
        parsed = parse_notice("a123", text)
        self.assertEqual(parsed["kind"], "failed")
        self.assertIsNone(parsed["recipient"])
        self.assertIn("Gmail sending limit reached", parsed["reason"])
        self.assertNotIn("address", parsed["reason"])
        self.assertIsNone(parse_notice("a123", text.replace("mailer-daemon@googlemail.com", "mailer-daemon@other.com")))
        self.assertIsNone(parse_notice("a123", text.replace("Subject: Re: " + SUBJECT, "Subject: Unrelated")))
        self.assertIsNone(parse_notice("a123", text.replace("You have reached", "The original email said: You have reached")))

    def test_check_sent_saves_sending_limit_and_reason_and_preserves_unselected_companies(self):
        from sent_checker import check_with_delivery
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            checked = Company(company_name="Checked", hr_email="hr@acme.com", status="sent", last_result="original receipt")
            untouched = Company(company_name="Other", hr_email="other@acme.com", status="sent")
            store._write([checked, untouched])
            text = (f"Thread ID: thread1\nSubject: Re: {SUBJECT}\nFrom: mailer-daemon@googlemail.com\n"
                    f"Date: {format_datetime(utcnow())}\n\nYou have reached a limit for sending mail. Your message was not sent.")
            async def read_tool(name, arguments):
                return "ID: a123\n" if name == "search_emails" else text
            connection = SimpleNamespace(read_tool=AsyncMock(side_effect=read_tool), find_sent=AsyncMock(return_value=[{
                "message_id": "sent123", "thread_id": "thread1", "date": format_datetime(utcnow() - timedelta(hours=1))}]))
            @asynccontextmanager
            async def connect():
                yield connection
            client = SimpleNamespace(connect=connect)
            state = root / ".local" / "delivery-monitor.json"
            report, result = asyncio.run(check_with_delivery(store, client, [checked], utcnow().date(), state))
            self.assertEqual(result["updated"], 1)
            self.assertEqual(report[0]["company"]["status"], "failed")
            self.assertIn("Gmail sending limit reached", report[0]["company"]["status_reason"])
            self.assertEqual(store.load()[0].last_result, "original receipt")
            self.assertEqual(store.load()[1], untouched)
            self.assertTrue(all(call.args[0] in ("search_emails", "read_email") for call in connection.read_tool.call_args_list))
            # A newer send in a different thread prevents an old limit reply from changing status.
            store._write([checked, untouched])
            connection.find_sent.return_value = [{"message_id": "new123", "thread_id": "new-thread", "date": format_datetime(utcnow())}]
            _, result = asyncio.run(check_with_delivery(store, client, [checked], utcnow().date(), state))
            self.assertEqual(result["updated"], 0)
            self.assertEqual(store.load()[0].status, "sent")

    def test_check_sent_button_opens_failed_view_for_confirmed_sending_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            company = Company(company_name="Acme", hr_email="hr@acme.com", status="sent")
            store._write([company])
            (root / "template.txt").write_text("Hello {company_name}", encoding="utf-8")
            text = (f"Thread ID: thread1\nSubject: Re: {SUBJECT}\nFrom: mailer-daemon@googlemail.com\n"
                    f"Date: {format_datetime(utcnow())}\n\nYou have reached a limit for sending mail. Your message was not sent.")
            async def read_tool(name, arguments):
                return "ID: a123\n" if name == "search_emails" else text
            connection = SimpleNamespace(read_tool=AsyncMock(side_effect=read_tool), find_sent=AsyncMock(return_value=[{
                "message_id": "sent123", "thread_id": "thread1", "date": format_datetime(utcnow() - timedelta(hours=1))}]))
            @asynccontextmanager
            async def connect():
                yield connection
            source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
            source = source.replace("ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            with patch("mcp_client.GmailMCPClient", return_value=SimpleNamespace(connect=connect)):
                app = AppTest.from_string(source, default_timeout=30).run()
                next(s for s in app.selectbox if s.label == "Company status to review").select("Sent").run()
                next(m for m in app.multiselect if m.key == "sent_check_companies").set_value([company.id]).run()
                next(b for b in app.button if b.label == "Check Gmail Sent").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(next(s for s in app.selectbox if s.label == "Company status to review").value, "Failed")
                self.assertEqual(store.load()[0].status, "failed")
                self.assertIn("Gmail sending limit reached", store.load()[0].status_reason)

    def test_older_button_requests_read_only_history_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            CompanyStore(root / "companies.json")._write([])
            script = ("import asyncio\nfrom pathlib import Path\nfrom core import CompanyStore\n"
                      "from delivery_monitor_ui import render_delivery_monitor\n"
                      f"root = Path({str(root)!r})\n"
                      "render_delivery_monitor(root, CompanyStore(root / 'companies.json'), asyncio.run)")
            with patch("delivery_monitor_ui.scan_delivery_reports", new_callable=AsyncMock,
                       return_value={"updated": 0, "inspected": 50}) as scan:
                app = AppTest.from_string(script, default_timeout=30).run()
                scan.assert_not_awaited()
                next(button for button in app.button if button.label == "Check older notices").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(scan.await_args.kwargs["older"])
                self.assertTrue(scan.await_args.kwargs["force"])

    def test_failed_older_read_does_not_advance_saved_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            store._write([Company(company_name="Acme", hr_email="hr@acme.com", status="sent")])
            state = root / "monitor.json"
            state.write_text('{"older_pending": ["a123", "b123"]}')
            original = state.read_bytes()
            queue = store.path.read_bytes()
            connection = SimpleNamespace(read_tool=AsyncMock(side_effect=RuntimeError("Connection stopped")))
            @asynccontextmanager
            async def connect():
                yield connection
            with self.assertRaises(RuntimeError):
                asyncio.run(scan_delivery_reports(store, SimpleNamespace(connect=connect), state, older=True))
            self.assertEqual(state.read_bytes(), original)
            self.assertEqual(store.path.read_bytes(), queue)

    def test_older_scan_resumes_buffer_saves_reasons_and_never_touches_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            company = Company(company_name="Acme", hr_email="hr@acme.com", status="sent")
            pending = Company(company_name="Waiting", hr_email="waiting@example.com", status="pending", delivery_state="failed")
            store._write([company, pending])
            identities = [f"{i:04x}" for i in range(1, 62)]
            old_date = utcnow() - timedelta(days=45)
            async def read_tool(name, args):
                if name == "search_emails":
                    self.assertIn("before:", args["query"])
                    self.assertNotIn("newer_than:30d", args["query"])
                    return "\n\n".join(f"ID: {identity}\nDate: {format_datetime(old_date)}" for identity in identities)
                return notice(date=old_date, recipient="waiting@example.com" if args["messageId"] == identities[-1] else "hr@acme.com")
            connection = SimpleNamespace(read_tool=AsyncMock(side_effect=read_tool), find_sent=AsyncMock(return_value=[{
                "message_id": "sent123", "thread_id": "thread1", "date": format_datetime(old_date - timedelta(days=1))}]))
            @asynccontextmanager
            async def connect():
                yield connection
            client = SimpleNamespace(connect=connect)
            state = root / ".local" / "delivery-monitor.json"
            first = asyncio.run(scan_delivery_reports(store, client, state, older=True))
            self.assertEqual(first["inspected"], 50)
            self.assertEqual(first["updated"], 1)
            self.assertFalse(first["older_complete"])
            self.assertEqual(len(load_monitor(state)["older_pending"]), 11)
            # Reloading from disk resumes the remaining batch without another search.
            second = asyncio.run(scan_delivery_reports(store, client, state, older=True))
            self.assertEqual(second["inspected"], 11)
            self.assertTrue(second["older_complete"])
            self.assertEqual(sum(call.args[0] == "search_emails" for call in connection.read_tool.call_args_list), 1)
            self.assertEqual(store.load()[0].status, "failed")
            self.assertIn("not found", store.load()[0].status_reason)
            self.assertEqual(store.load()[1], pending)
            self.assertEqual(connection.find_sent.call_args.args[1].year, 1970)
            before = connection.read_tool.await_count
            asyncio.run(scan_delivery_reports(store, client, state, older=True))
            self.assertEqual(connection.read_tool.await_count, before)

    def test_older_scan_overlaps_full_page_dates_and_does_not_skip_ambiguous_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = CompanyStore(root / "companies.json")
            store._write([Company(company_name="Acme", hr_email="hr@acme.com", status="sent")])
            state = root / ".local" / "delivery-monitor.json"
            date = utcnow() - timedelta(days=40)
            metadata = "\n\n".join(f"ID: {i:04x}\nDate: {format_datetime(date)}" for i in range(500))
            connection = SimpleNamespace(read_tool=AsyncMock(return_value=metadata))
            @asynccontextmanager
            async def connect():
                yield connection
            client = SimpleNamespace(connect=connect)
            # Previously seen messages can advance a full older page once, with a one-second overlap.
            state.parent.mkdir()
            import json
            state.write_text(json.dumps({"seen": [f"{i:04x}" for i in range(500)]}))
            asyncio.run(scan_delivery_reports(store, client, state, older=True))
            self.assertEqual(load_monitor(state)["older_before"], int(date.timestamp()) + 1)
            self.assertFalse(load_monitor(state)["older_exhausted"])
            original = state.read_bytes()
            with self.assertRaisesRegex(ValueError, "time boundary"):
                asyncio.run(scan_delivery_reports(store, client, state, older=True))
            self.assertEqual(state.read_bytes(), original)

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
        self.assertEqual(load_monitor(path)["latest_events"], [])
        self.assertEqual(len(load_monitor(path)["events"]), 1)
        self.assertEqual(store.load()[0].status_reason, "Recipient email address was not found.")

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
