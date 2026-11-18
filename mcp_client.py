"""Scoped stdio sessions for the Gmail MCP server. Never falls back to send."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from datetime import timedelta

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core import CC, SUBJECT, EMAIL, validate_pdf


class GmailConnection:
    def __init__(self, session, tools):
        self.session = session
        self.tools = {tool.name: tool for tool in tools}

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

    async def deliver(self, mode, payload):
        tool = self.require_tool(mode)
        # Validate again at the transport boundary, including fixed CC/subject.
        if payload.get("cc") != [CC] or payload.get("subject") != SUBJECT:
            raise ValueError("Mandatory CC or subject changed")
        recipients = payload.get("to", [])
        if len(recipients) != 1 or not EMAIL.fullmatch(recipients[0]):
            raise ValueError("Exactly one valid HR recipient is required")
        if not payload.get("body", "").strip() or any(c in payload["body"] for c in "{}"):
            raise ValueError("Body is empty or contains unresolved placeholders")
        if len(payload.get("attachments", [])) != 1:
            raise ValueError("Exactly one PDF CV is required")
        validate_pdf(payload["attachments"][0])
        Draft202012Validator(tool.inputSchema).validate(payload)
        result = await self.session.call_tool(tool.name, arguments=payload)
        content = [block.model_dump(mode="json") for block in result.content]
        summary = json.dumps({"content": content, "structuredContent": result.structuredContent}, ensure_ascii=False)
        if result.isError:
            raise RuntimeError(summary)
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

    async def test_connection(self):
        async with self.connect() as connection:
            availability = {}
            for mode in ("draft", "send"):
                try:
                    availability[mode] = connection.require_tool(mode).name
                except ValueError as exc:
                    availability[mode] = str(exc)
            return availability
