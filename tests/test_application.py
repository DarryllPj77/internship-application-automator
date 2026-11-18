import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, TextContent
from streamlit.testing.v1 import AppTest

from core import (CC, SUBJECT, Company, CompanyStore, atomic_text, email_payload,
                  exclusive_lock, import_companies, render_template, run_batch)
from mcp_client import GmailConnection, GmailMCPClient

ROOT = Path(__file__).resolve().parents[1]


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / "CV with spaces.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n%%EOF")
        self.company = Company(company_name="Acme", hr_email="hr@acme.com",
                               contact_person="Hiring Team", relevant_skills="Python")
        self.store = CompanyStore(self.root / "companies.json")
        self.store._write([self.company])

    def payload(self):
        return email_payload(self.company, "Dear {contact_person}, {company_name}: {relevant_skills}", str(self.pdf))

    def test_fixed_payload_and_absolute_cv(self):
        payload = self.payload()
        self.assertEqual(payload["cc"], [CC])
        self.assertEqual(payload["subject"], SUBJECT)
        self.assertEqual(payload["attachments"], [str(self.pdf.resolve())])
        self.assertEqual(payload["body"], "Dear Hiring Team, Acme: Python")

    def test_validation_blocks_bad_cv_email_tokens_and_sample_recipients(self):
        for value in ["bad", "a@b", "x@y.com\nBcc: other@z.com", "a@b.com,c@d.com"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Company(**{**self.company.model_dump(), "hr_email": value})
        for template in ["{missing}", "", "Dear {company_name", "Dear }"]:
            with self.subTest(template=template), self.assertRaises(ValueError):
                email_payload(self.company, template, str(self.pdf))
        sample = self.company.model_copy(update={"hr_email": "hr@company.example"})
        with self.assertRaises(ValueError):
            email_payload(sample, "Hi", str(self.pdf))
        wrong_extension = self.root / "CV.txt"
        wrong_extension.write_bytes(b"%PDF-1.4")
        with self.assertRaises(ValueError):
            email_payload(self.company, "Hi", str(wrong_extension))
        self.pdf.write_bytes(b"not a pdf")
        with self.assertRaises(ValueError):
            self.payload()
        self.pdf.unlink()
        with self.assertRaises(ValueError):
            self.payload()

    def test_replacements_are_single_pass(self):
        company = self.company.model_copy(update={"company_name": "{contact_person}"})
        self.assertEqual(render_template("{company_name}", company), "{contact_person}")

    def test_import_atomic_validation_and_duplicate_history(self):
        self.store.update(self.company.id, status="sent")
        current = self.store.load()
        imported = import_companies(json.dumps([{
            **self.company.model_dump(), "status": "pending"}]).encode(), "input.json", current)
        self.assertEqual(imported, current)
        raw = b"company_name,hr_email,contact_person,relevant_skills\nOther,other@acme.com,HR,SQL"
        result = import_companies(raw, "input.csv", current)
        self.assertEqual(result[-1].status, "pending")
        with self.assertRaises(ValueError):
            import_companies(b'[{}]', "input.json", current)
        self.assertEqual(self.store.load(), current)

    def test_optimistic_persistence_and_lock(self):
        original = self.store.load()
        self.store.update(self.company.id, status="drafted")
        with self.assertRaises(ValueError):
            self.store.replace(original, original)
        with exclusive_lock(self.store.batch_lock):
            with self.assertRaises(ValueError):
                self.store.replace(self.store.load(), self.store.load())
        self.assertFalse(self.store.batch_lock.exists())

    def test_rows_without_ids_have_stable_identity(self):
        data = self.company.model_dump(exclude={"id"})
        atomic_text(self.store.path, json.dumps([data]))
        first = self.store.load()
        self.assertEqual(first, self.store.load())
        self.store.replace(first, first)

    def test_sent_rows_are_unselected_in_dashboard_defaults(self):
        # Batch receives only explicit selections, never discovers targets itself.
        company = self.company.model_copy(update={"status": "sent"})
        self.store._write([company])
        client = SimpleNamespace(connect=lambda: self.fail("Must not connect"))
        with self.assertRaises(ValueError):
            asyncio.run(run_batch(self.store, client, [], "Hi", str(self.pdf), "send", lambda *args: None))
        self.assertEqual(self.store.load()[0].status, "sent")

    def test_schema_rejects_missing_attachments_and_draft_never_falls_back(self):
        tool = SimpleNamespace(name="send_email", inputSchema={"properties": {}})
        connection = GmailConnection(None, [tool])
        with self.assertRaises(ValueError):
            connection.require_tool("draft")
        with self.assertRaises(ValueError):
            connection.require_tool("send")

    def test_transport_handles_mcp_error(self):
        schema = {"type": "object", "properties": {key: {} for key in self.payload()}}
        tool = SimpleNamespace(name="draft_email", inputSchema=schema)
        session = SimpleNamespace(call_tool=AsyncMock(return_value=CallToolResult(
            isError=True, content=[TextContent(type="text", text="provider rejected")])) )
        with self.assertRaises(RuntimeError):
            asyncio.run(GmailConnection(session, [tool]).deliver("draft", self.payload()))
        self.assertEqual(session.call_tool.call_args.args[0], "draft_email")

    def test_batch_delays_and_persists_success(self):
        second = self.company.model_copy(update={"id": "second", "hr_email": "other@acme.com"})
        self.store._write([self.company, second])
        events, calls = [], []
        store = self.store
        class FakeClient:
            @asynccontextmanager
            async def connect(self):
                yield self
            def require_tool(self, mode):
                return SimpleNamespace(name=mode + "_email")
            async def deliver(self, mode, payload):
                # Recovery marker must already be durable before external call.
                self_row = next(c for c in store.load() if c.hr_email == payload["to"][0])
                assert self_row.needs_review
                calls.append((mode, payload))
                return "ok-id"
        sleep = AsyncMock()
        with patch("core.random.randint", return_value=17):
            asyncio.run(run_batch(self.store, FakeClient(), [self.company, second],
                "Hello {company_name}", str(self.pdf), "send", lambda *event: events.append(event), sleep))
        self.assertEqual(sleep.await_count, 17)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c.status == "sent" and not c.needs_review for c in self.store.load()))
        self.assertEqual([v for k, v in events if k == "countdown"], list(range(17, 0, -1)) + [0])

    def test_failure_stops_without_retry_and_blocks_future_attempt(self):
        class BrokenClient:
            calls = 0
            @asynccontextmanager
            async def connect(self):
                yield self
            def require_tool(self, mode):
                return SimpleNamespace(name="draft_email")
            async def deliver(self, mode, payload):
                self.calls += 1
                raise TimeoutError("unknown delivery outcome")
        client = BrokenClient()
        asyncio.run(run_batch(self.store, client, [self.company], "Hi", str(self.pdf), "draft", lambda *args: None))
        current = self.store.load()
        self.assertEqual(current[0].status, "failed")
        self.assertTrue(current[0].needs_review)
        with self.assertRaises(ValueError):
            asyncio.run(run_batch(self.store, client, current, "Hi", str(self.pdf), "draft", lambda *args: None))
        self.assertEqual(client.calls, 1)

    def test_entire_batch_validated_before_connect(self):
        client = SimpleNamespace(connect=lambda: self.fail("Must not connect"))
        with self.assertRaises(ValueError):
            asyncio.run(run_batch(self.store, client, [self.company], "{unknown}", str(self.pdf), "draft", lambda *args: None))

    def test_real_stdio_discovery_and_draft_call_offline(self):
        async def exercise():
            client = GmailMCPClient(sys.executable, [str(ROOT / "tests" / "fake_mcp_server.py")])
            async with client.connect() as connection:
                self.assertEqual(connection.require_tool("draft").name, "draft_email")
                result = await connection.deliver("draft", self.payload())
                self.assertIn("fixture-draft-id:123", result)
        asyncio.run(exercise())


class DashboardTests(unittest.TestCase):
    def test_confirmed_draft_batch_through_dashboard_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(company_name="Offline Company", hr_email="hr@acme.com",
                              contact_person="Hiring Team", relevant_skills="Python")
            store = CompanyStore(root / "companies.json")
            store._write([company])
            atomic_text(root / "template.txt", "Dear {contact_person}, hello {company_name}.")
            pdf = root / "CV.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            environment = {"CV_FILE_PATH": str(pdf), "MCP_SERVER_COMMAND": sys.executable,
                           "MCP_SERVER_ARGS": json.dumps([str(ROOT / "tests" / "fake_mcp_server.py")])}
            with patch.dict(os.environ, environment):
                app = AppTest.from_string(code, default_timeout=30)
                app.session_state["selected_ids"] = [company.id]
                app.run()
                self.assertFalse(app.exception)
                def button(label):
                    return next(b for b in app.button if b.label == label)
                button("Create Drafts for Selected (1)").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(button("Confirm and start").disabled)
                app.checkbox[0].check().run()
                button("Confirm and start").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(store.load()[0].status, "drafted")
                self.assertFalse(store.load()[0].needs_review)
                self.assertEqual(app.session_state["selected_ids"], [])

    def test_dashboard_renders_and_preview_changes(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.toggle[0].value, False)
        self.assertEqual(len(app.metric), 4)
        self.assertIn("Northstar", app.selectbox[0].value.company_name)
        app.selectbox[0].select_index(1).run()
        self.assertFalse(app.exception)
        self.assertIn("Evergreen", app.selectbox[0].value.company_name)


if __name__ == "__main__":
    unittest.main()
