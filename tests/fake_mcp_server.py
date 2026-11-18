"""Offline real stdio fixture; never connects to Gmail."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("offline-gmail-fixture")


@server.tool()
def draft_email(to: list[str], cc: list[str], subject: str, body: str, attachments: list[str]) -> str:
    return "fixture-draft-id:123"


@server.tool()
def send_email(to: list[str], cc: list[str], subject: str, body: str, attachments: list[str]) -> str:
    return "fixture-message-id:456"


if __name__ == "__main__":
    server.run(transport="stdio")
