import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mcp.types import CallToolResult, TextContent
from core import Company, CompanyStore, email_payload, run_batch
from mail_errors import GmailAuthError, mail_error_message
from mcp_client import GmailConnection, GmailMCPClient, delivery_receipt


def result(text="", *, is_error=False):
    return CallToolResult(content=[TextContent(type="text", text=text)] if text else [], isError=is_error)


class MailReliabilityTests(unittest.TestCase):
    def test_unflagged_auth_errors_and_json_errors_are_not_success(self):
        for text in ("Error: invalid_grant", '{"error":"invalid_grant"}'):
            for mode in ("draft", "send"):
                with self.assertRaises(GmailAuthError):
                    delivery_receipt(result(text), mode)

    def test_receipt_is_required_and_matches_the_operation(self):
        self.assertEqual(delivery_receipt(result("Email draft created successfully with ID: r-123"), "draft"), "r-123")
        self.assertEqual(delivery_receipt(result('{"id":"abc123"}'), "send"), "abc123")
        for response in (result(), result("OK"), result("Email sent successfully with ID: abc123")):
            with self.assertRaises(RuntimeError):
                delivery_receipt(response, "draft")

    def test_task_group_exposes_actionable_auth_error(self):
        error = ExceptionGroup("unhandled errors in a TaskGroup", [ExceptionGroup("nested", [GmailAuthError("invalid_grant")])])
        message = mail_error_message(error)
        self.assertIn("Reconnect Gmail", message)
        self.assertNotIn("TaskGroup", message)

    def test_connection_test_checks_google_instead_of_just_listing_tools(self):
        connection = SimpleNamespace(read_tool=AsyncMock(return_value=""),
                                     require_tool=lambda mode: SimpleNamespace(name=mode + "_email"))
        @asynccontextmanager
        async def connect():
            yield connection
        client = GmailMCPClient()
        client.connect = connect
        self.assertEqual(asyncio.run(client.test_connection())["draft"], "draft_email")
        connection.read_tool.assert_awaited_once_with("search_emails", {"query": "in:drafts", "maxResults": 1})
        connection.read_tool.side_effect = GmailAuthError("invalid_grant")
        with self.assertRaises(GmailAuthError):
            asyncio.run(client.test_connection())

    def exercise_batch(self, response=None, *, cancelled=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pdf = root / "cv.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            companies = [Company(company_name="First", hr_email="hr@first.com"),
                         Company(company_name="Second", hr_email="hr@second.com")]
            store = CompanyStore(root / "companies.json")
            store._write(companies)
            payload = email_payload(companies[0], "Hello", str(pdf))
            session = SimpleNamespace(call_tool=AsyncMock(return_value=response))
            schema = {"type": "object", "properties": {field: {} for field in payload}}
            connection = GmailConnection(session, [SimpleNamespace(name="draft_email", inputSchema=schema)])
            if cancelled:
                session.call_tool.side_effect = asyncio.CancelledError()
            @asynccontextmanager
            async def connect():
                yield connection
            operation = run_batch(store, SimpleNamespace(connect=connect), companies, "Hello", str(pdf), "draft", lambda *_: None)
            if cancelled:
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(operation)
            else:
                asyncio.run(operation)
            saved = store.load()
            self.assertEqual(session.call_tool.await_count, 1)
            self.assertEqual(saved[0].status, "failed")
            self.assertEqual(saved[1].status, "pending")
            self.assertFalse(store.batch_lock.exists())
            return saved

    def test_auth_error_stops_batch_and_never_marks_drafted(self):
        saved = self.exercise_batch(result("Error: invalid_grant"))
        self.assertFalse(saved[0].needs_review)
        self.assertIn("Reconnect Gmail", saved[0].last_result)

    def test_missing_receipt_preserves_uncertainty(self):
        self.assertTrue(self.exercise_batch(result())[0].needs_review)

    def test_refresh_cancellation_preserves_recovery_marker(self):
        self.assertTrue(self.exercise_batch(cancelled=True)[0].needs_review)
