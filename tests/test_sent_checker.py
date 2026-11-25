import asyncio
from contextlib import asynccontextmanager
from datetime import date
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mcp.types import CallToolResult, TextContent
from core import Company, CompanyStore, SUBJECT
from mcp_client import GmailConnection
from sent_checker import check_drafted, apply_sent_checks


def reply(text):
    return CallToolResult(content=[TextContent(type="text", text=text)])


class SentCheckTests(unittest.TestCase):
    def connection(self, responses):
        session = SimpleNamespace(call_tool=AsyncMock(side_effect=responses))
        tools = [SimpleNamespace(name=name, inputSchema={"type": "object"})
                 for name in ("search_emails", "read_email")]
        return GmailConnection(session, tools), session

    def test_reads_sent_and_verifies_exact_headers_never_sends(self):
        connection, session = self.connection([reply("ID: a123\nSubject: test\n"),
            reply(f"Thread ID: b123\nSubject: {SUBJECT}\nFrom: Sender <sender@example.com>\nTo: HR <hr@example.com>\nDate: Fri, 20 Nov 2026 10:00:00 +0000\n\nBody")])
        matches = asyncio.run(connection.find_sent("hr@example.com", date(2026, 11, 1)))
        self.assertEqual(matches[0]["message_id"], "a123")
        calls = session.call_tool.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["search_emails", "read_email"])
        self.assertIn("in:sent", calls[0].kwargs["arguments"]["query"])
        self.assertIn("after:2026/11/01", calls[0].kwargs["arguments"]["query"])

    def test_body_mentions_do_not_count_as_recipient_or_subject(self):
        for subject, recipient in (("Different subject", "hr@example.com"), (SUBJECT, "other@example.com")):
            connection, _ = self.connection([reply("ID: a123\n"),
                reply(f"Subject: {subject}\nTo: {recipient}\nDate: today\n\nTo: hr@example.com\nSubject: {SUBJECT}")])
            self.assertEqual(asyncio.run(connection.find_sent("hr@example.com", date.today())), [])

    def test_empty_search_and_errors_never_mark_sent(self):
        connection, _ = self.connection([reply("")])
        self.assertEqual(asyncio.run(connection.find_sent("hr@example.com", date.today())), [])
        connection, _ = self.connection([CallToolResult(isError=True, content=[])])
        with self.assertRaises(RuntimeError):
            asyncio.run(connection.find_sent("hr@example.com", date.today()))
        connection, _ = self.connection([reply("unexpected output")])
        with self.assertRaises(ValueError):
            asyncio.run(connection.find_sent("hr@example.com", date.today()))

    def test_reviewed_update_is_explicit_scoped_and_rejects_stale_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CompanyStore(Path(folder) / "companies.json")
            first = Company(company_name="Acme", hr_email="hr@acme.com", status="drafted", last_result="Original draft ID")
            second = Company(company_name="Other", hr_email="hr@other.com", status="drafted")
            store._write([first, second])
            report = [{"company": first.model_dump(), "matches": [{"message_id": "a123"}]},
                      {"company": second.model_dump(), "matches": []}]
            with self.assertRaises(ValueError):
                apply_sent_checks(store, report, [second.id])
            self.assertEqual(apply_sent_checks(store, report, [first.id]), 1)
            self.assertEqual([c.status for c in store.load()], ["sent", "drafted"])
            self.assertIn("Original draft ID", store.load()[0].last_result)
            with self.assertRaises(ValueError):
                apply_sent_checks(store, report, [first.id])

    def test_discovery_does_not_change_queue(self):
        company = Company(company_name="Acme", hr_email="hr@acme.com", status="drafted")
        connection = SimpleNamespace(find_sent=AsyncMock(return_value=[]))
        @asynccontextmanager
        async def connect():
            yield connection
        result = asyncio.run(check_drafted(SimpleNamespace(connect=connect), [company], date.today()))
        self.assertFalse(result[0]["matches"])
        self.assertEqual(company.status, "drafted")
