# Internship Desk

A local Streamlit dashboard for Darryll Pajaganas's Internship 1 applications.
Creates Gmail drafts by default, or sends explicitly selected applications after
review and confirmation. Uses the Gmail MCP subprocess, not SMTP or an LLM.

## Start locally (Windows PowerShell)

Install Python 3.11–3.14 and Node.js LTS with npm first. Python 3.13 is recommended.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set the absolute path to your PDF CV.
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open [the dashboard](http://127.0.0.1:8501). It binds to loopback by default.
No PowerShell activation or execution-policy changes are necessary.
On macOS/Linux use `python3 -m venv .venv`, `.venv/bin/python`, and set
`MCP_SERVER_COMMAND=npx`. Paths with spaces are supported. Relative CV paths are
resolved against the directory from which Streamlit was launched; prefer absolute paths.

## Google Cloud OAuth and Gmail MCP setup

1. Open [Google Cloud Console](https://console.cloud.google.com/), create/select
   a project, and enable **Gmail API** in the API Library.
2. Configure the Google Auth Platform consent screen (branding, audience, data
   access). For an external app in testing, add the Gmail account you will use as
   a test user. A school-managed account may require your administrator's approval.
3. Create an OAuth client in **APIs & Services → Credentials → Create credentials
   → OAuth client ID**. Choose **Desktop app**, as supported by the Gmail MCP
   server. Alternatively choose **Web application** and register exactly
   `http://localhost:3000/oauth2callback` as an authorized redirect URI.
4. Download the client JSON and rename it `gcp-oauth.keys.json`. Store it outside
   this project, in `$env:USERPROFILE\.gmail-mcp`:

   ```powershell
   New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.gmail-mcp"
   Copy-Item "$env:USERPROFILE\Downloads\gcp-oauth.keys.json" "$env:USERPROFILE\.gmail-mcp\gcp-oauth.keys.json"
   npx.cmd -y @gongrzhe/server-gmail-autoauth-mcp auth
   ```

5. Complete browser sign-in and consent. Keep port 3000 available during this
   step. The server stores tokens in `~/.gmail-mcp/credentials.json`. Its current
   source requests Gmail modify and settings-basic access; read the consent screen.
6. Return to the dashboard and click **Test MCP Connection**. This launches the
   server over stdio, initializes a session, and lists its tools. The subprocess
   closes after the test and reconnects for each batch. “Connected” means the
   last transport/discovery check succeeded; it does not validate Gmail tokens.
7. Replace the `.example` sample recipients with verified company addresses,
   select one company, review its preview, and create a draft. Check Gmail for
   the body, CC, and PDF before using Send Mode.

**The OAuth account is the actual Gmail sender.** The school email in the signature
does not change the Gmail From address. The server's tool schema does not offer
a From field; authenticate the intended sending account. The app neither changes
your Gmail account nor impersonates a school address.

Setup references: [Gmail MCP upstream setup](https://github.com/GongRzhe/Gmail-MCP-Server#installation--authentication),
[Google OAuth desktop flow](https://developers.google.com/identity/protocols/oauth2/native-app),
[Enable Google Workspace APIs](https://developers.google.com/workspace/guides/enable-apis),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
The upstream repository is archived; runtime schema checks reject tools without
the necessary attachment and email fields. `MCP_SERVER_ARGS` can select a specific reviewed
package version or another compatible local stdio server. The default follows
the requested `npx -y @gongrzhe/server-gmail-autoauth-mcp` invocation.

## Configuration

`.env` accepts:

| Variable | Meaning |
| --- | --- |
| `CV_FILE_PATH` | Absolute path to the local PDF resume |
| `MCP_SERVER_COMMAND` | Executable, normally `npx.cmd` on Windows or `npx` elsewhere |
| `MCP_SERVER_ARGS` | JSON array of argument strings; never a shell command string |

The PDF path input overrides the environment setting for the current session.
To retain a new path after restarting, edit `.env`. A valid file must exist, have
a `.pdf` extension, and start with a PDF signature. This checks the file type,
not whether its pages contain a complete or correct CV.

CC and BCC are optional and empty by default. Expand **Optional CC / BCC
recipients** to enter any email addresses, separated by commas or semicolons.
Clear a field to remove its copy recipients. Valid edits save automatically to
local, Git-ignored `email_settings.json` and load again in future sessions.
Invalid addresses block execution, and duplicates within a field are removed
case-insensitively. An address cannot appear in both CC and BCC.

Saved copies apply automatically to **every** draft or email in a batch. Review
them in Email preview and the confirmation dialog. Confirmation freezes these
addresses for that batch; subsequent setting changes affect future batches.
BCC is shown to you in the local preview/confirmation but hidden from other email
recipients. The MCP server must advertise support for any populated copy field.
No school address is automatically added. For a self-test, leave both fields empty.
Previously created Gmail drafts and sent messages are not modified by these edits.

Fixed subject:

```text
FEU TECH - DARRYLL PAJAGANAS - Internship Application - BSCSSE - 2TSY2627 - Internship 1
```

## Dashboard workflow

- **Configuration:** test MCP discovery, enter the CV path, and choose Draft or
  Send Mode. Draft is the default. No email is processed by a connection test.
- **Companies:** edit company/contact/skills/email cells inline; valid edits
  persist automatically. Status is managed by batch results. Select individual
  rows or all pending rows. Sent rows are never selected automatically; manually
  checking a sent row explicitly permits processing it again, with a warning in
  confirmation. Selections clear after every batch.
- **Import:** upload UTF-8 CSV or a JSON array, then click Import. Required fields
  are `company_name`, `hr_email`, `contact_person`, `relevant_skills`.
  Import is all-or-nothing for malformed rows, skips duplicate HR addresses
  case-insensitively, and initializes new rows as Pending. Imported IDs/statuses
  cannot overwrite previous delivery history.
- **Template:** text edits save to `template.txt`; placeholder chips append tokens.
  Choose a company for an exact plain-text preview. Unresolved tokens appear red,
  and remaining braces block execution. The portfolio appears as a plain URL in
  the outgoing plain-text message.
- **Execution:** the confirmation dialog lists all recipients and lets you inspect
  every rendered body. A confirmation is consumed once. A batch validates all
  selected applications before opening MCP. Draft mode only calls `draft_email`
  or `create_draft`, never `send_email`. Send mode only calls `send_email` and
  waits a random 15–30 seconds between successful calls, with a live countdown.
- **Results:** each successful operation updates `companies.json` immediately.
  Activity includes tool responses and can be downloaded. Logs are session-local;
  each company's latest result and recovery marker persist in the JSON file.

CSV example:

```csv
company_name,hr_email,contact_person,relevant_skills
Example Company,careers@example.com,Hiring Team,"C#, Python, and SQL"
```

Sample `.example`/`.invalid`/`.test` recipients are blocked from execution. The
regex validates syntax, not mailbox existence or the company's legitimacy.

## Recovery and limits

The application records a `needs_review` marker before each mail call. Errors,
timeouts, crashes, or uncertain replies leave that marker in place, stop the
batch, and prevent retries until reconciled. Check Gmail **Sent and Drafts**,
then use **Review interrupted / failed operations** to record the verified
outcome. Choose Failed only after verifying that no application was created.
There is no automatic retry: Gmail and local JSON cannot form one transaction.
If Gmail accepts a mail but the local save fails, this review is necessary.

The company store uses atomic replacement, a write lock, and optimistic conflict
checks; one batch may run at a time per project directory. Keep one dashboard
tab open for this personal workspace. Do not edit `companies.json` externally
during a batch. Template editing is intended for one active user session.

If the app was force-closed and a lock remains, **first stop all Streamlit
processes for this project**, inspect/reconcile uncertain Gmail outcomes, and
then remove only this project's `companies.batch.lock` / `companies.write.lock`
if present. Never remove a lock while a batch is active. Restart the dashboard.

Startup/discovery times out after 90 seconds; individual MCP requests after 60
seconds. First-time npm downloads can exceed the startup timeout: run the auth
command in a terminal first. OAuth expiration/revocation requires reauthentication.
If Node is missing from PATH, restart your terminal after installation.

The UI is a local personal tool, without accounts or a public deployment layer.
It does not read mail, verify the connected account, enforce Gmail quotas, or
attempt to cancel/recall accepted messages. Rate limiting reduces burst traffic;
it does not guarantee delivery or exemption from Gmail sending limits.
Keep `.env`, OAuth credentials, and any exported logs private. `companies.json`
contains application contacts and results; review it before committing.

## Code map and verification

| File | Responsibility |
| --- | --- |
| `app.py` | Four dashboard sections, confirmation, orchestration, streaming events |
| `core.py` | Models, rendering, CV validation, atomic persistence/import, batch runner |
| `mcp_client.py` | Async stdio lifecycle, paginated discovery, schema checks, tool calls |
| `ui.py`, `ui/` | Presentation helpers, dashboard tokens, accessible editable company table |
| `static/fonts/` | Locally served Inter and JetBrains Mono fonts with OFL licenses |
| `DESIGN.md` | Dashboard layout, typography, color, and interaction decisions |
| `DESIGN_REVIEW.md` | Verification results, checker limitations, and open findings |
| `companies.json` | Local company records, delivery states, recovery metadata |
| `email_settings.json` | Optional local CC/BCC preferences, created on edit and ignored by Git |
| `template.txt` | Editable applicant-specific plain-text template |
| `tests/` | Offline guardrail, persistence, batch, UI, and stdio integration tests |

Run tests without Gmail credentials or any real email calls:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/company_table.test.cjs
```

The light theme uses crisp slate surfaces (#F8FAFC canvas, #FFFFFF cards,
#F1F5F9 inputs and previews, #E2E8F0 borders), Corporate Cobalt accents, and four semantic status
palettes. Company fields save on blur or Enter; the table supports search, page
sizes, and selecting the visible page. Selections are retained across searches
and pages. Template and Email preview tabs share one writing panel. Reduced-motion
preferences disable animation. Fonts are bundled locally; no font-service network
request is needed. Restart Streamlit after changing its server/static-file settings.
