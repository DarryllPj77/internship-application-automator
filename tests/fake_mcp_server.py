"""Offline real stdio fixture; never connects to Gmail."""
import json

from mcp.server.fastmcp import FastMCP

server = FastMCP("offline-gmail-fixture")


@server.tool()
def draft_email(to: list[str], cc: list[str], subject: str, body: str, attachments: list[str], bcc: list[str] | None = None) -> str:
    return json.dumps({"id": "fixture-draft-id:123", "to": to, "cc": cc, "bcc": bcc or []})


@server.tool()
def send_email(to: list[str], cc: list[str], subject: str, body: str, attachments: list[str], bcc: list[str] | None = None) -> str:
    return json.dumps({"id": "fixture-message-id:456", "to": to, "cc": cc, "bcc": bcc or []})


if __name__ == "__main__":
    server.run(transport="stdio")
