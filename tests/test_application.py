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

from core import (SUBJECT, Company, CompanyStore, EmailSettings, atomic_text, email_payload,
                  exclusive_lock, import_companies, render_template, run_batch,
                  load_email_settings, save_email_settings, save_uploaded_cv)
from mcp_client import GmailConnection, GmailMCPClient, email_html
from ui import preview_metadata, status_pill

ROOT = Path(__file__).resolve().parents[1]


class ApplicationTests(unittest.TestCase):
    def test_resend_requires_exact_explicit_sent_recipients_and_send_mode(self):
        sent = self.company.model_copy(update={"status": "sent"})
        self.store._write([sent])
        client = SimpleNamespace(connect=lambda: self.fail("Invalid resend must not connect"))
        for mode, ids, rows in (("draft", [sent.id], [sent]), ("send", ["wrong"], [sent]),
                                ("send", [sent.id, "extra"], [sent]), ("send", [sent.id], [self.company])):
            with self.assertRaises(ValueError):
                asyncio.run(run_batch(self.store, client, rows, "Hi", str(self.pdf), mode,
                    lambda *args: None, resend_ids=ids))
        calls = []
        class ResendClient:
            @asynccontextmanager
            async def connect(self):
                yield self
            def require_tool(self, mode):
                return SimpleNamespace(name="send_email")
            async def deliver(self, mode, payload):
                calls.append((mode, payload["to"]))
                return "Resent offline"
        asyncio.run(run_batch(self.store, ResendClient(), [sent], "Hi", str(self.pdf), "send",
            lambda *args: None, resend_ids=[sent.id]))
        self.assertEqual(calls, [("send", [sent.hr_email])])
        self.assertEqual(self.store.load()[0].status, "sent")

    def test_sent_company_blocks_entire_draft_or_send_batch_before_connection(self):
        sent = self.company.model_copy(update={"id": "already-sent", "hr_email": "sent@acme.com", "status": "sent"})
        self.store._write([self.company, sent])
        before = self.store.load()
        client = SimpleNamespace(connect=lambda: self.fail("Sent batch must never connect to Gmail"))
        for mode in ("draft", "send"):
            with self.assertRaisesRegex(ValueError, "Already Sent"):
                asyncio.run(run_batch(self.store, client, [self.company, sent], "Hi", str(self.pdf), mode, lambda *args: None))
            self.assertEqual(self.store.load(), before)

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
        self.assertEqual(payload["cc"], [])
        self.assertNotIn("bcc", payload)
        self.assertEqual(payload["subject"], SUBJECT)
        self.assertEqual(payload["attachments"], [str(self.pdf.resolve())])
        self.assertEqual(payload["body"], "Dear Hiring Team, Acme: Python")

    def test_uploaded_pdf_is_saved_safely_and_used_as_attachment(self):
        data = b"%PDF-1.4\nUploaded CV\n%%EOF"
        directory = self.root / "uploads" / "cvs"
        saved = save_uploaded_cv(directory, "../../CV with spaces.PDF", data)
        self.assertTrue(saved.is_relative_to(directory.resolve()))
        self.assertEqual(saved.name, "CV with spaces.pdf")
        self.assertEqual(saved.read_bytes(), data)
        self.assertEqual(email_payload(self.company, "Hi", str(saved))["attachments"], [str(saved)])
        self.assertEqual(save_uploaded_cv(directory, "CV with spaces.PDF", data), saved)
        self.assertEqual(save_uploaded_cv(directory, "CON.pdf", data).name, "CV-CON.pdf")

    def test_changed_upload_does_not_overwrite_confirmed_attachment(self):
        directory = self.root / "uploads"
        first = save_uploaded_cv(directory, "resume.pdf", b"%PDF-1.4\nfirst")
        confirmed = email_payload(self.company, "Hi", str(first))
        second = save_uploaded_cv(directory, "resume.pdf", b"%PDF-1.4\nsecond")
        self.assertNotEqual(first, second)
        self.assertEqual(Path(confirmed["attachments"][0]).read_bytes(), b"%PDF-1.4\nfirst")

    def test_invalid_uploads_are_rejected_before_creating_files(self):
        directory = self.root / "uploads"
        for name, data in [("cv.txt", b"%PDF-1.4"), ("cv.pdf", b"not a PDF"), ("cv.pdf", b"")]:
            with self.subTest(name=name, data=data), self.assertRaises(ValueError):
                save_uploaded_cv(directory, name, data)
        with patch("core.MAX_CV_UPLOAD_BYTES", 8), self.assertRaisesRegex(ValueError, "20 MB"):
            save_uploaded_cv(directory, "cv.pdf", b"%PDF-1.4\nToo big")
        self.assertFalse(directory.exists())

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

    def test_html_email_escapes_content_and_has_no_fixed_width(self):
        rendered = email_html('Dear A & B,\n\nA long paragraph <script>alert(1)</script>.\nSignature\nhttps://example.com')
        self.assertIn('A &amp; B', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('<br>Signature', rendered)
        self.assertIn('<a href="https://example.com">', rendered)
        self.assertNotIn('max-width', rendered)
        self.assertNotIn('<pre', rendered)

    def test_transport_adds_html_alternative_only_when_supported(self):
        original = self.payload()
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {key: {} for key in original}}
        session = SimpleNamespace(call_tool=AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text='{"id":"offline-confirmed-id"}')])))
        tool = SimpleNamespace(name="draft_email", inputSchema=schema)
        connection = GmailConnection(session, [tool])
        asyncio.run(connection.deliver("draft", original))
        self.assertEqual(session.call_tool.call_args.kwargs['arguments'], original)
        schema['properties'].update({'htmlBody': {'type': 'string'},
                                    'mimeType': {'enum': ['text/plain', 'multipart/alternative']}})
        asyncio.run(connection.deliver("draft", original))
        delivered = session.call_tool.call_args.kwargs['arguments']
        self.assertEqual(delivered['mimeType'], 'multipart/alternative')
        self.assertEqual(delivered['body'], original['body'])
        self.assertEqual(delivered['attachments'], original['attachments'])
        self.assertIn('<p ', delivered['htmlBody'])
        self.assertNotIn('htmlBody', original)

    def test_transport_validates_optional_copies_for_drafts_and_sends(self):
        schema = {"type": "object", "properties": {key: {} for key in self.payload()}}
        schema["properties"]["bcc"] = {"type": "array", "items": {"type": "string"}}
        tools = [SimpleNamespace(name=name, inputSchema=schema) for name in ("draft_email", "send_email")]
        session = SimpleNamespace(call_tool=AsyncMock(return_value=CallToolResult(
            content=[TextContent(type="text", text='{"id":"offline-confirmed-id"}')])))
        connection = GmailConnection(session, tools)
        for mode in ("draft", "send"):
            for field in ("cc", "bcc"):
                with self.subTest(mode=mode, field=field), self.assertRaises(ValueError):
                    asyncio.run(connection.deliver(mode, {**self.payload(), field: ["invalid-address"]}))
        session.call_tool.assert_not_awaited()
        for mode, name in (("draft", "draft_email"), ("send", "send_email")):
            payload = {**self.payload(), "cc": ["copy@example.com"], "bcc": ["private@example.com"]}
            asyncio.run(connection.deliver(mode, payload))
            self.assertEqual(session.call_tool.call_args.args[0], name)
            self.assertEqual(session.call_tool.call_args.kwargs["arguments"]["cc"], ["copy@example.com"])
            self.assertEqual(session.call_tool.call_args.kwargs["arguments"]["bcc"], ["private@example.com"])

    def test_optional_copy_settings_validate_persist_and_clear(self):
        path = self.root / "email_settings.json"
        self.assertEqual(load_email_settings(path), EmailSettings())
        settings = EmailSettings(cc="first@example.com; FIRST@example.com, second@example.com", bcc="private@example.com")
        self.assertEqual(settings.cc, ["first@example.com", "second@example.com"])
        save_email_settings(path, settings)
        self.assertEqual(load_email_settings(path), settings)
        save_email_settings(path, EmailSettings(cc="", bcc=""))
        self.assertEqual(load_email_settings(path), EmailSettings())
        for invalid in ("invalid", "a@example.com\nBcc: attacker@example.com"):
            with self.assertRaises(ValueError):
                EmailSettings(cc=invalid)
        with self.assertRaises(ValueError):
            EmailSettings(cc="same@example.com", bcc="SAME@example.com")

    def test_unsupported_copy_field_is_blocked_before_tool_call(self):
        tool = SimpleNamespace(name="send_email", inputSchema={"properties": {key: {} for key in self.payload()}})
        session = SimpleNamespace(call_tool=AsyncMock())
        with self.assertRaisesRegex(ValueError, "does not support BCC"):
            asyncio.run(GmailConnection(session, [tool]).deliver("send", {**self.payload(), "bcc": ["private@example.com"]}))
        session.call_tool.assert_not_awaited()

    def test_batch_automatically_reuses_confirmed_copies_for_each_company(self):
        second = self.company.model_copy(update={"id": "second", "hr_email": "other@acme.com"})
        calls = []
        class FakeClient:
            @asynccontextmanager
            async def connect(self):
                yield self
            def require_tool(self, mode):
                return SimpleNamespace(name=mode + "_email")
            async def deliver(self, mode, payload):
                calls.append((mode, payload))
                return "offline-id"
        settings_path = self.root / "email_settings.json"
        confirmed = EmailSettings(cc="review@example.com", bcc="private@example.com")
        save_email_settings(settings_path, EmailSettings(cc="future@example.com"))
        for mode in ("draft", "send"):
            self.store._write([self.company, second])
            asyncio.run(run_batch(self.store, FakeClient(), [self.company, second], "Hi", str(self.pdf), mode,
                lambda *args: None, AsyncMock(), cc=confirmed.cc, bcc=confirmed.bcc))
        self.assertEqual(len(calls), 4)
        for mode, payload in calls:
            self.assertEqual(payload["cc"], ["review@example.com"])
            self.assertEqual(payload["bcc"], ["private@example.com"])
        self.assertEqual(load_email_settings(settings_path).cc, ["future@example.com"])

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
    def test_resend_flow_requires_user_selection_send_mode_and_extra_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sent = Company(company_name="Resend target", hr_email="hr@example.com", status="sent")
            other = Company(company_name="Not selected", hr_email="other@example.com", status="sent")
            store = CompanyStore(root / "companies.json")
            store._write([sent, other])
            atomic_text(root / "template.txt", "Hello {company_name}")
            pdf = root / "CV.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            environment = {"CV_FILE_PATH": str(pdf), "MCP_SERVER_COMMAND": sys.executable,
                           "MCP_SERVER_ARGS": json.dumps([str(ROOT / "tests" / "fake_mcp_server.py")])}
            with patch.dict(os.environ, environment):
                app = AppTest.from_string(code, default_timeout=30).run()
                button = lambda label: next(b for b in app.button if b.label == label)
                button("Resend sent emails…").click().run()
                self.assertEqual(app.session_state.workspace_section, "batch")
                self.assertEqual(app.session_state.resend_company_ids, [])
                next(m for m in app.multiselect if m.key == "resend_company_ids").set_value([sent.id]).run()
                self.assertTrue(button("Review resend (1)").disabled)
                next(t for t in app.toggle if t.key == "send_mode").set_value(True).run()
                button("Review resend (1)").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(store.load(), [sent, other])
                next(c for c in app.checkbox if c.label.startswith("I reviewed To")).check().run()
                self.assertTrue(button("Confirm and start").disabled)
                next(c for c in app.checkbox if c.key == "confirm_resend_acknowledged").check().run()
                button("Confirm and start").click().run()
                self.assertFalse(app.exception)
                saved = store.load()
                self.assertEqual(saved[0].status, "sent")
                self.assertIn("fixture-message-id", saved[0].last_result.lower())
                self.assertEqual(saved[1], other)
                self.assertEqual(app.session_state.resend_company_ids, [])

    def test_stale_sent_selection_is_removed_from_batch_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sent = Company(company_name="Sent company", hr_email="sent@company.com", status="sent")
            store = CompanyStore(root / "companies.json")
            store._write([sent])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            with patch("ui.company_table", return_value={"rows": [sent.model_dump()], "selected_ids": [sent.id]}):
                app = AppTest.from_string(code, default_timeout=30)
                app.session_state["selected_ids"] = [sent.id]
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["selected_ids"], [])
                self.assertTrue(any(b.label == "Create Drafts for Selected (0)" and b.disabled for b in app.button))
                self.assertEqual(store.load()[0].status, "sent")

    def test_upload_activates_cv_and_clear_preserves_a_manual_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(company_name="Upload Test", hr_email="hr@acme.com",
                              contact_person="HR", relevant_skills="Python")
            CompanyStore(root / "companies.json")._write([company])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            data = b"%PDF-1.4\nUploaded CV"
            uploaded = SimpleNamespace(name="Uploaded CV.pdf", getvalue=lambda: data)
            events = [uploaded]
            def uploader(label, **kwargs):
                import streamlit as st
                if label == "Upload PDF CV" and events:
                    st.session_state.cv_upload = events.pop(0)
                    kwargs["on_change"]()
                return None
            with patch.dict(os.environ, {"CV_FILE_PATH": ""}), patch("streamlit.file_uploader", side_effect=uploader):
                app = AppTest.from_string(code, default_timeout=30).run()
                self.assertFalse(app.exception)
                path_input = next(t for t in app.text_input if t.label == "PDF CV path")
                saved_path = Path(path_input.value)
                self.assertEqual(saved_path.read_bytes(), data)
                self.assertTrue(any("Valid PDF Found" in item.value for item in app.markdown))
                events.append(None)
                app.run()
                self.assertEqual(next(t for t in app.text_input if t.label == "PDF CV path").value, "")
                self.assertTrue(saved_path.exists())
                events.append(uploaded)
                app.run()
                manual = root / "manual.pdf"
                manual.write_bytes(b"%PDF-1.4\nManual CV")
                next(t for t in app.text_input if t.label == "PDF CV path").set_value(str(manual)).run()
                events.append(None)
                app.run()
                self.assertEqual(next(t for t in app.text_input if t.label == "PDF CV path").value, str(manual))
                events.append(SimpleNamespace(name="bad.pdf", getvalue=lambda: b"invalid"))
                app.run()
                self.assertFalse(app.exception)
                self.assertEqual(next(t for t in app.text_input if t.label == "PDF CV path").value, "")
                self.assertTrue(any("PDF signature" in error.value for error in app.error))

    def test_preview_metadata_escapes_user_content(self):
        rendered = preview_metadata('<img src=x onerror=alert(1)>', SUBJECT, 'CV.pdf')
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;img', rendered)
        self.assertIn('email-subject', rendered)
        self.assertIn('Cc', rendered)
        self.assertIn('Bcc', rendered)
        self.assertIn('None', rendered)
        self.assertIn('status-sent', status_pill('sent'))

    def test_company_component_edit_and_selection_use_validated_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(company_name="Original", hr_email="hr@acme.com",
                              contact_person="HR", relevant_skills="Python")
            store = CompanyStore(root / "companies.json")
            store._write([company])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            event = {"rows": [{**company.model_dump(), "company_name": "Edited"}], "selected_ids": [company.id]}
            with patch('ui.company_table', return_value=event):
                app = AppTest.from_string(code, default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(store.load()[0].company_name, "Edited")
            self.assertEqual(app.session_state["selected_ids"], [company.id])
            event["rows"][0]["hr_email"] = "invalid-address"
            with patch('ui.company_table', return_value=event):
                app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Edits not saved' in error.value for error in app.error))
            self.assertEqual(store.load()[0].hr_email, "hr@acme.com")

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
                next(t for t in app.text_input if t.label == "CC recipients (optional)").set_value("copy@example.com").run()
                next(t for t in app.text_input if t.label == "BCC recipients (optional)").set_value("private@example.com").run()
                self.assertEqual(load_email_settings(root / "email_settings.json").cc, ["copy@example.com"])
                def button(label):
                    return next(b for b in app.button if b.label == label)
                button("Create Drafts for Selected (1)").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any("copy@example.com" in text.value and "private@example.com" in text.value for text in app.text))
                self.assertTrue(button("Confirm and start").disabled)
                app.checkbox[0].check().run()
                button("Confirm and start").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(store.load()[0].status, "drafted")
                self.assertIn("copy@example.com", store.load()[0].last_result)
                self.assertIn("private@example.com", store.load()[0].last_result)
                self.assertFalse(store.load()[0].needs_review)
                self.assertEqual(app.session_state["selected_ids"], [])

    def test_dashboard_renders_and_preview_changes(self):
        # UI tests must not depend on or modify the applicant's live queue.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            CompanyStore(root / "companies.json")._write([
                Company(company_name="Northstar", hr_email="careers@northstar.example"),
                Company(company_name="Evergreen", hr_email="internships@evergreen.example")])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(code, default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.toggle[0].value, False)
            self.assertEqual(len(app.metric), 4)
            self.assertFalse(any(item.label == "Preview company" for item in app.selectbox))
            companies = CompanyStore(root / "companies.json").load()
            app.session_state["selected_ids"] = [c.id for c in companies]
            app.run()
            preview = next(item for item in app.selectbox if item.label == "Preview company")
            self.assertIn("Northstar", preview.options[0])
            preview.select_index(1).run()
            self.assertFalse(app.exception)
            self.assertTrue(any("internships@evergreen.example" in item.value for item in app.markdown))
            app.session_state["selected_ids"] = [companies[0].id]
            app.run()
            preview = next(item for item in app.selectbox if item.label == "Preview company")
            self.assertEqual(len(preview.options), 1)
            self.assertIn("Northstar", preview.options[0])
            app.session_state["selected_ids"] = []
            app.run()
            self.assertFalse(any(item.label == "Preview company" for item in app.selectbox))

    def test_queue_edit_and_delete_update_live_preview_and_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = Company(company_name="First", hr_email="first@company.com", relevant_skills="SQL")
            second = Company(company_name="Second", hr_email="second@company.com", relevant_skills="Python")
            store = CompanyStore(root / "companies.json")
            store._write([first, second])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            app = AppTest.from_string(code, default_timeout=30)
            app.session_state['preview_company_id'] = second.id
            app.session_state['selected_ids'] = [second.id]
            action = {"type": "edit", "nonce": "edit-once", "id": second.id,
                      "changes": {"company_name": "Updated Second", "hr_email": "updated@company.com", "contact_person": "", "relevant_skills": "", "status": "drafted"}}
            with patch('ui.company_table', return_value={"action": action}):
                app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['preview_company_id'], second.id)
            self.assertEqual(store.load()[1].status, "drafted")
            self.assertTrue(any('updated@company.com' in item.value for item in app.markdown))
            with patch('ui.company_table', return_value={"action": {"type": "delete", "nonce": "delete-once", "ids": [second.id]}}):
                app.run()
            self.assertFalse(app.exception)
            self.assertEqual([c.id for c in store.load()], [first.id])
            self.assertEqual(app.session_state['selected_ids'], [])
            self.assertFalse(any(item.label == "Preview company" for item in app.selectbox))

    def test_sidebar_navigation_preserves_queue_and_unfinished_form_inputs(self):
        from workspace_navigation import SECTIONS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(company_name="Acme", hr_email="hr@acme.com", status="drafted")
            store = CompanyStore(root / "companies.json")
            store._write([company])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            with patch('ui.company_table', return_value=None):
                app = AppTest.from_string(code, default_timeout=30)
                app.session_state['selected_ids'] = [company.id]
                app.run()
                self.assertEqual(app.session_state['workspace_section'], 'settings')
                self.assertEqual(next(iter(SECTIONS)), 'settings')
                self.assertEqual(list(SECTIONS)[-1], 'batch')
                self.assertFalse(next(t for t in app.toggle if t.key == 'send_mode').value)
                next(t for t in app.toggle if t.key == 'send_mode').set_value(True).run()
                self.assertTrue(any(b.label == 'Send Emails to Selected (1)' for b in app.button))
                next(t for t in app.text_input if t.key == "new_company_name").set_value("Unfinished company").run()
                next(t for t in app.text_input if t.key == "new_company_skills_text").set_value("SQL and Python").run()
                next(t for t in app.text_input if t.key == "cv_path").set_value("pending-resume.pdf").run()
                for section in SECTIONS:
                    next(r for r in app.radio if r.key == "workspace_section").set_value(section).run()
                    self.assertFalse(app.exception)
                    self.assertEqual([metric.value for metric in app.metric], ["0", "1", "0", "0"])
                    self.assertFalse(any("st-key-application_metrics" in item.value and "display:none!important" in item.value
                                         for item in app.markdown))
                    self.assertEqual(app.session_state['selected_ids'], [company.id])
                    self.assertEqual(app.session_state['new_company_name'], "Unfinished company")
                    self.assertEqual(app.session_state['new_company_skills_text'], "SQL and Python")
                    self.assertEqual(app.session_state['cv_path'], "pending-resume.pdf")
                    self.assertTrue(app.session_state['send_mode'])
                    self.assertEqual(store.load()[0].status, "drafted")

    def test_stale_queue_action_cannot_delete_a_company(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(company_name="Protected", hr_email="hr@company.com")
            store = CompanyStore(root / "companies.json")
            store._write([company])
            atomic_text(root / "template.txt", "Hello {company_name}")
            code = (ROOT / "app.py").read_text(encoding="utf-8").replace(
                "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")
            with patch('ui.company_table', return_value={"stale": True, "action": {"type": "delete", "nonce": "old", "ids": [company.id]}}):
                app = AppTest.from_string(code, default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(any('queue changed' in error.value for error in app.error))
            self.assertEqual(len(store.load()), 1)


if __name__ == "__main__":
    unittest.main()
