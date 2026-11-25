"""Scoped stdio sessions for the Gmail MCP server. Never falls back to send."""
from __future__ import annotations

import asyncio
import json
import html
import os
import re
import shutil
from contextlib import asynccontextmanager
from datetime import timedelta
from email.utils import getaddresses

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core import SUBJECT, EMAIL, EmailSettings, validate_pdf
from mail_errors import AUTH_MESSAGE, GmailAuthError, is_auth_error, mail_error_message


def verify_tool_result(result):
    """This server sometimes returns Error: text without setting isError."""
    texts = [block.text for block in result.content if block.type == "text"]
    structured = result.structuredContent
    errors = [text for text in texts if re.match(r"\s*(?:error|failed|failure)\s*[:\-]", text, re.I)]
    for text in texts:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("error"):
            errors.append(str(data["error"]))
    if isinstance(structured, dict) and structured.get("error"):
        errors.append(str(structured["error"]))
    if result.isError or errors:
        error = RuntimeError("\n".join(errors or texts) or "Gmail tool reported an error")
        if is_auth_error(error):
            raise GmailAuthError(AUTH_MESSAGE)
        raise RuntimeError(mail_error_message(error))
    return texts


def delivery_receipt(result, mode):
    texts = verify_tool_result(result)
    pattern = r"Email draft created successfully with ID:\s*([\w:-]+)" if mode == "draft" else r"Email sent successfully with ID:\s*([\w:-]+)"
    candidates = [result.structuredContent]
    for text in texts:
        match = re.fullmatch(pattern, text.strip())
        if match:
            return match[1]
        try:
            candidates.append(json.loads(text))
        except ValueError:
            pass
    for data in candidates:
        if isinstance(data, dict) and isinstance(data.get("id"), str) and re.fullmatch(r"[\w:-]+", data["id"]):
            return data["id"]
    raise RuntimeError("Gmail did not return a confirmed message/draft ID. Check Gmail before retrying; the outcome is uncertain.")


def email_html(body: str) -> str:
    """Escape template text and preserve paragraphs without a fixed-width layout."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = []
    for paragraph in re.split(r"\n[ \t]*\n", body):
        escaped = html.escape(paragraph).replace("\n", "<br>")
        escaped = re.sub(r"https?://[^\s<>]+", lambda m: f'<a href="{m[0]}">{m[0]}</a>', escaped)
        paragraphs.append('<p style="margin:0 0 16px;">' + escaped + '</p>')
    return ('<!doctype html><html><head><meta charset="UTF-8"></head><body>'
            '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;overflow-wrap:break-word;">'
            + "".join(paragraphs) + '</div></body></html>')


class GmailConnection:
    def __init__(self, session, tools):
        self.session = session
        self.tools = {tool.name: tool for tool in tools}

    async def read_tool(self, name, arguments):
        if name not in ("search_emails", "read_email") or name not in self.tools:
            raise ValueError(f"Gmail MCP must provide the read-only {name} tool for sent checking")
        Draft202012Validator(self.tools[name].inputSchema).validate(arguments)
        result = await self.session.call_tool(name, arguments=arguments)
        return "\n".join(verify_tool_result(result))

    async def find_sent(self, recipient, since):
        if not EMAIL.fullmatch(recipient):
            raise ValueError("Invalid recipient for sent check")
        # Search only Sent; independently verify exact Subject and To headers.
        query = f'in:sent to:({recipient}) subject:"{SUBJECT}" after:{since:%Y/%m/%d}'
        text = await self.read_tool("search_emails", {"query": query, "maxResults": 5})
        if text.strip() and not re.search(r"^ID: [a-fA-F0-9]+\s*$", text, re.M):
            raise ValueError("Unrecognized Gmail search response; no status was changed")
        found = []
        for identity in dict.fromkeys(re.findall(r"^ID: ([a-fA-F0-9]+)\s*$", text, re.M)):
            message = await self.read_tool("read_email", {"messageId": identity})
            header = message.replace("\r\n", "\n").split("\n\n", 1)[0]
            headers = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
            addresses = {address.casefold() for _, address in getaddresses([headers.get("To", "")])}
            if headers.get("Subject") == SUBJECT and addresses == {recipient.casefold()}:
                found.append({"message_id": identity, "date": headers.get("Date", "Unknown"),
                              "sender": headers.get("From", "Unknown")})
        return found

    def require_tool(self, mode):
        names = {"draft": ("draft_email", "create_draft"), "send": ("send_email",)}
        if mode not in names:
            raise ValueError("Unknown mode")
        for name in names[mode]:
            if name in self.tools:
                tool = self.tools[name]
                fields = tool.inputSchema.get("properties", {})
                missing = set(("to", "cc", "subject", "body", "attachments")) - fields.keys()
                if missing:
                    raise ValueError(f"{name} does not advertise required fields: {', '.join(sorted(missing))}")
                return tool
        raise ValueError(f"No {mode} tool available. Discovered: {', '.join(self.tools)}")

    def validate_payload(self, mode, payload):
        tool = self.require_tool(mode)
        settings = EmailSettings(cc=payload.get("cc"), bcc=payload.get("bcc"))
        for field, recipients in (("cc", settings.cc), ("bcc", settings.bcc)):
            if recipients and field not in tool.inputSchema.get("properties", {}):
                raise ValueError(f"{tool.name} does not support {field.upper()} recipients")
        if payload.get("subject") != SUBJECT:
            raise ValueError("Fixed subject changed")
        recipients = payload.get("to", [])
        if len(recipients) != 1 or not EMAIL.fullmatch(recipients[0]):
            raise ValueError("Exactly one valid HR recipient is required")
        if not payload.get("body", "").strip() or any(c in payload["body"] for c in "{}"):
            raise ValueError("Body is empty or contains unresolved placeholders")
        if len(payload.get("attachments", [])) != 1:
            raise ValueError("Exactly one PDF CV is required")
        validate_pdf(payload["attachments"][0])
        Draft202012Validator(tool.inputSchema).validate(payload)
        return tool

    async def deliver(self, mode, payload):
        tool = self.validate_payload(mode, payload)
        fields = tool.inputSchema.get("properties", {})
        mime_types = fields.get("mimeType", {}).get("enum", [])
        if "htmlBody" in fields and "multipart/alternative" in mime_types:
            payload = {**payload, "htmlBody": email_html(payload["body"]), "mimeType": "multipart/alternative"}
            self.validate_payload(mode, payload)
        result = await self.session.call_tool(tool.name, arguments=payload)
        receipt = delivery_receipt(result, mode)
        content = [block.model_dump(mode="json") for block in result.content]
        summary = json.dumps({"content": content, "structuredContent": result.structuredContent,
                              "receipt": {"mode": mode, "id": receipt}}, ensure_ascii=False)
        return summary


class GmailMCPClient:
    def __init__(self, command=None, args=None):
        self.command = command or os.getenv("MCP_SERVER_COMMAND") or ("npx.cmd" if os.name == "nt" else "npx")
        self.args = args if args is not None else json.loads(os.getenv(
            "MCP_SERVER_ARGS", '["-y", "@gongrzhe/server-gmail-autoauth-mcp"]'))
        if not isinstance(self.args, list) or not all(isinstance(arg, str) for arg in self.args):
            raise ValueError("MCP_SERVER_ARGS must be a JSON array of strings")

    @asynccontextmanager
    async def connect(self):
        command = shutil.which(self.command)
        if not command:
            raise ValueError(f"MCP command not found: {self.command}. Install Node.js and restart the terminal.")
        params = StdioServerParameters(command=command, args=self.args, env=dict(os.environ))
        # Startup, discovery, and requests are bounded. Keep all contexts on one task.
        try:
            async with asyncio.timeout(90) as startup_timeout:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60)) as session:
                        await session.initialize()
                        tools = []
                        cursor = None
                        while True:
                            page = await session.list_tools(cursor=cursor)
                            tools.extend(page.tools)
                            cursor = page.nextCursor
                            if not cursor:
                                break
                        connection = GmailConnection(session, tools)
                        # Only startup is timed; batches can legitimately run for hours.
                        startup_timeout.reschedule(None)
                        yield connection

        except Exception as exc:
            if is_auth_error(exc):
                raise GmailAuthError(AUTH_MESSAGE) from None
            if getattr(exc, "exceptions", None):
                raise RuntimeError(mail_error_message(exc)) from None
            raise

    async def test_connection(self):
        async with self.connect() as connection:
            # Listing tools only proves the process started, not Google access.
            await connection.read_tool("search_emails", {"query": "in:drafts", "maxResults": 1})
            availability = {}
            for mode in ("draft", "send"):
                try:
                    availability[mode] = connection.require_tool(mode).name
                except ValueError as exc:
                    availability[mode] = str(exc)
            return availability
