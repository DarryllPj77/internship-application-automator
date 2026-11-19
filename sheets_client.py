"""Read-only Google Sheets adapter. Authentication is an explicit local CLI action."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from core import atomic_text

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / ".local" / "sheets-token.json"


def save_token(token_file: Path, credentials):
    token_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(token_file, credentials.to_json())


def spreadsheet_reference(url: str) -> tuple[str, int | None]:
    parsed = urlparse(url.strip())
    match = re.fullmatch(r"/spreadsheets/d/([\w-]+)(?:/.*)?", parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com" or not match:
        raise ValueError("Paste an https://docs.google.com/spreadsheets/d/... URL")
    values = {**parse_qs(parsed.query), **parse_qs(parsed.fragment)}
    try:
        gid = int(values["gid"][0]) if "gid" in values else None
    except ValueError as exc:
        raise ValueError("Invalid worksheet gid") from exc
    return match[1], gid


def authenticate(client_file: Path, token_file: Path = TOKEN_FILE):
    from google_auth_oauthlib.flow import InstalledAppFlow
    import json
    config = json.loads(client_file.read_text(encoding="utf-8-sig"))
    if "installed" not in config:
        raise ValueError("Create a Desktop app OAuth client for Sheets; keep your Gmail client unchanged")
    # Fail before opening consent if local credential storage cannot be created.
    token_file.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_config(config, SCOPES, autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host="127.0.0.1", port=0, timeout_seconds=900,
                                        access_type="offline", prompt="consent select_account")
    if not credentials.has_scopes(SCOPES):
        raise ValueError("Read-only Sheets permission was not granted")
    save_token(token_file, credentials)


class SheetsReader:
    def __init__(self, token_file: Path = TOKEN_FILE):
        self.token_file = token_file

    def service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        if not self.token_file.exists():
            raise ValueError("Sheets is not connected. Run the Sheets sign-in command shown below first")
        credentials = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if not credentials.valid:
            if not credentials.refresh_token:
                raise ValueError("Sheets sign-in expired. Run the sign-in command again")
            credentials.refresh(Request())
            save_token(self.token_file, credentials)
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def worksheets(self, url: str) -> list[dict]:
        sheet_id, _ = spreadsheet_reference(url)
        service = self.service()
        try:
            result = service.spreadsheets().get(spreadsheetId=sheet_id,
                fields="sheets(properties(sheetId,title))").execute()
            return [s["properties"] for s in result.get("sheets", [])]
        finally:
            service.close()

    def read(self, url: str, title: str) -> list[list[str]]:
        sheet_id, _ = spreadsheet_reference(url)
        service = self.service()
        try:
            # Bounded read; merged cells remain blank and multirow headers are mapped in the UI.
            result = service.spreadsheets().values().get(spreadsheetId=sheet_id,
                range="'" + title.replace("'", "''") + "'!A1:AZ5000",
                valueRenderOption="FORMATTED_VALUE").execute()
            return result.get("values", [])
        finally:
            service.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Connect read-only Google Sheets separately from Gmail")
    parser.add_argument("auth", choices=["auth"])
    parser.add_argument("--client-file", default=os.getenv("SHEETS_CLIENT_FILE", ""))
    args = parser.parse_args()
    try:
        if not args.client_file:
            raise ValueError("Set SHEETS_CLIENT_FILE in .env or pass --client-file PATH")
        authenticate(Path(args.client_file).expanduser())
        print("Google Sheets connected with read-only access. Return to Company sources in Internship Desk.")
    except Exception as exc:
        parser.exit(1, f"Sheets connection failed ({type(exc).__name__}). Check your client file, consent, and network.\n")
