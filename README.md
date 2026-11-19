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

Upload your PDF using **Upload PDF CV**, or paste an existing local path. Uploads
are limited to 20 MB and checked for a `.pdf` extension and PDF signature before
being selected. The chosen file fills **PDF CV path** and is automatically used
in previews and confirmed draft/send batches.

Uploads are saved under local, Git-ignored `uploads/cvs/`, outside the public
static folder. Different PDF contents get different directories, so replacing an
upload does not overwrite a previously confirmed attachment. A safe version of
the original filename is retained for Gmail. Clearing the upload deselects it
when its saved path is still active; a manually entered replacement path is kept.
Removing the selection does not delete the saved local file. Uploading by itself
does not send anything to Gmail.

The PDF path input overrides the environment setting for the current session.
After restarting or opening a new session, upload again or paste the saved path.
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
  persist automatically. Use the pencil action to edit all fields and status,
  including resetting a completed row to Pending. Blank contact and skills fields
  default to `Hiring Team` and `software development`. Select individual
  rows or all pending rows. Sent rows are never selected automatically; manually
  checking a sent row explicitly permits processing it again, with a warning in
  confirmation. Selections clear after every batch.
- **Remove companies:** the trash action removes one row after confirmation.
  **Delete Selected (N)** removes the complete selection, including rows selected
  on other pages or hidden by the current search. Cancel leaves the queue intact.
  Removing a queue record does not delete, recall, or modify any Gmail messages.
  Edits/removals are blocked during an active mail batch. An uncertain delivery
  must be reconciled before its status can be changed; the edit modal does not
  bypass recovery review. Edits keep the same stable company ID, so its active
  email preview refreshes without switching to another company. Deleting the
  previewed company selects the next available preview, or shows the empty state.
  All row action buttons leave batch selection unchanged unless their confirmed
  deletion removes a selected row. Queue mutations invalidate an open batch
  confirmation so recipients must be reviewed again before mail execution.
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

### Optional FastAPI queue manager

The main mail dashboard remains Streamlit at port 8501. A standalone queue page
and REST API use the same `companies.json` and the same validation/atomic store:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open [the API queue page](http://127.0.0.1:8000/) or
[interactive API documentation](http://127.0.0.1:8000/docs).
The standalone queue page calls the REST endpoints below. The embedded Streamlit
table uses its component bridge to the same store and requires no second server.
Both render the shared `static/index.html`; it contains edit/status and remove
confirmation dialogs. The standalone page includes a live body/recipient preview;
use the main dashboard to review CV attachments, optional copies, or execute mail
batches. Changes made in the other queue view appear on the next refresh/rerun.

| Method | Endpoint | Request / result |
| --- | --- | --- |
| GET | `/api/companies` | Full queue |
| PUT | `/api/companies/{id}` | Company name, HR email, contact, skills, status; returns full updated queue |
| DELETE | `/api/companies/{id}` | Removes one record; returns full updated queue |
| POST | `/api/companies/bulk-delete` | `{"ids": ["company-id", "another-id"]}`; returns full updated queue |
| GET | `/api/preview/{id}` | Current To, subject, rendered template body |

Malformed input returns 422, an unknown individual ID returns 404, and an active
batch, conflicting edit, or unreconciled status change returns 409. Bulk deletion
removes matching IDs in one atomic write, ignores unknown IDs, and does not require
index-based identifiers. IDs remain stable when a company's email address changes.
The API is intended for local loopback use. Pydantic request validation and the
test setup follow the [FastAPI request-body](https://fastapi.tiangolo.com/tutorial/body/)
and [testing](https://fastapi.tiangolo.com/tutorial/testing/) documentation.

| File | Responsibility |
| --- | --- |
| `app.py` | Four dashboard sections, confirmation, orchestration, streaming events |
| `main.py` | Optional local FastAPI company edit/delete and preview API |
| `core.py` | Models, rendering, CV validation, atomic persistence/import, batch runner |
| `mcp_client.py` | Async stdio lifecycle, paginated discovery, schema checks, tool calls |
| `ui.py`, `ui/` | Presentation helpers and dashboard tokens |
| `static/index.html` | Shared company table, edit/delete dialogs, and standalone API queue page |
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

The light theme uses mint surfaces (#D1FAE5 canvas, #ECFDF5 cards,
#F4FBF8 inputs and previews, #A7F3D0 borders), Deep Emerald accents, and four semantic status
palettes. Company fields save on blur or Enter; the table supports search, page
sizes, and selecting the visible page. Selections are retained across searches
and pages. Template and Email preview tabs share one writing panel. Reduced-motion
preferences disable animation. Fonts are bundled locally; no font-service network
request is needed. Restart Streamlit after changing its server/static-file settings.

## Company directory, Google Sheets, and opportunity research

Open **Company sources & opportunities** above the company queue, or use
[the expanded source workspace](http://127.0.0.1:8501/?sources=1).
The Streamlit app reads Sheets directly through Google's API. An optional local
MCP server exposes the same read-only directory access for MCP clients.
Neither source path calls Gmail or automatically starts an application batch.

### Connect Google Sheets once

1. In the same Google Cloud project used for Gmail, enable
   [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com).
2. Use a **Desktop app** OAuth client from Google Auth Platform → Clients.
   You can reuse the Gmail client JSON if its top-level key is `installed`.
   A Web application client requires a separate Desktop client for this flow.
3. Set `SHEETS_CLIENT_FILE` in your local `.env` to that JSON's absolute path.
   Optionally set `SHEETS_URL` to prefill the directory URL. Do not commit `.env`
   or OAuth credentials. If the consent app is in Testing, add the Google account
   that can view the directory under Audience → Test users.
4. Install the updated dependencies, then authorize from the project terminal:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe sheets_client.py auth
   ```

   Choose the account that can open the spreadsheet. Grant read-only Sheets
   access. The callback uses a temporary loopback port with a 15-minute timeout.
   Tokens are kept in ignored `.local/sheets-token.json`, separately from Gmail.
   Re-run this command when authorization expires or to choose another account.
5. In the app, paste the spreadsheet URL, click **Connect / list worksheets**,
   choose the worksheet, then **Read worksheet**. The URL's `gid` selects the
   initial tab. Reads are bounded to A1:AZ5000 and never modify the source.

If Google reports insufficient access, sign in using the account that has access,
or request access from the owner. The XLSX badge means the source may still be
an Excel workbook: use **Upload Excel / CSV**, or a Google Sheets copy you are
permitted to create. No public sharing or school-sheet editing is required.

Google setup references: [Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python),
[read-only scope](https://developers.google.com/workspace/sheets/api/scopes).

### Review and import contacts

Both Google Sheets and Excel/CSV use the same preview and column mapping.
Excel/CSV uploads allow up to 10 MB, 5,000 rows, and 52 columns. Formulas are
not evaluated. Select the actual worksheet, first data row, company column,
POC name, POC job title, email, industry, and address columns.

For the supplied FEU directory layout: first data row **4**, company **B**,
POC name **E**, POC position **F**, POC email **G**, industry **C**, address **D**.
These are editable mappings, not assumed headers. POC Position is the contact's
job title, not a vacancy. To import POC 2, map that group's columns and review again;
each queue row represents one selected contact and email address.

Check **Include** for the contacts you want and edit incorrect cells in the
preview before **Add reviewed contacts to queue**. Missing or invalid emails
start unchecked and are never guessed. Importing a checked invalid address
rejects the entire import. Existing email addresses are skipped case-insensitively;
existing company edits, Sent/Drafted status, recovery markers, and application
results are preserved. New contacts start Pending. Source and row provenance
are saved in `companies.json`. Re-reading a directory does not automatically
overwrite contacts or update changed email addresses; review those manually.

### Research roles and technology mentions

Under **Roles & tech stacks**, choose an imported company/POC. Paste a specific
posting URL and click **Read posting & suggest details**. Public HTTPS HTML pages
can be read directly. For LinkedIn, JobStreet, sign-in pages, blocked sites, or
JavaScript-only job pages, paste the posting text alongside its source URL.
No LinkedIn/JobStreet account connection or automated account scraping is used.

The reader extracts a suggested title, technology keyword mentions, and posting/
expiry dates when JobPosting structured data supplies them. These are suggestions,
not proof of an active opening or a complete company technology stack. Review
the company match, edit the role and technologies, and confirm before saving.
Unknown technologies and dates stay Unknown. It does not search job boards for
you, confirm applications are open, or infer a stack from an industry label.

Saved postings retain their source, checked timestamp, review state, and notes.
Saving the same source URL replaces that contact's previous research snapshot.
They are visible in the research panel and summarized in the queue. Remove a
saved posting from its details panel if needed. Applicant `relevant_skills`,
email templates, recipients, and application statuses are not modified by research.
All queue writes respect the existing batch lock and concurrent-edit detection.
There is no LLM/API-token usage for the deterministic import and keyword reader.

### Optional read-only Sources MCP server

After Sheets authorization, an MCP client can launch the local stdio server with
the absolute Python executable and script paths (JSON backslashes must be escaped):

```json
{
  "mcpServers": {
    "internship-sources": {
      "command": "E:\\Darryll pogi\\ResumeForJOB\\AutomatedApplication\\.venv\\Scripts\\python.exe",
      "args": ["E:\\Darryll pogi\\ResumeForJOB\\AutomatedApplication\\sources_mcp.py"]
    }
  }
}
```

Adapt paths and configuration syntax for your MCP client. The server exposes only
`list_directory_worksheets` and `read_directory_worksheet`; it cannot edit Sheets,
change the queue, or send emails. Cell values are external data, not instructions.
This is separate from the existing Gmail MCP server. The app does not need an
additional MCP connection to use its built-in directory importer.

## FEU Partner Job Matcher

Open [the partner matcher](http://127.0.0.1:8501/?matcher=1), below the status
counters. This workspace is separate from the email queue: it includes partners
without HR addresses and never creates drafts, sends emails, or changes applicant
skills. A row in a selected FEU directory tab is not proof of a current partnership
agreement. Keep the source tab and its date in mind when applying.

### Partner names and search links (no key needed)

1. Click **Load worksheets for matching**, select your partner worksheet, and
   confirm the first data row and company-name column. For GENERAL MASTERLIST,
   use **row 4 / column B**. Other tabs can have different layouts.
2. Click **Load partner companies & build search links**. Duplicate company names
   are merged after normalizing punctuation and trailing legal suffixes; parent
   companies, subsidiaries, and different geographic entities remain separate.
   Source row numbers and the selected worksheet are preserved.
3. Choose a location. Each row searches by the shortened company name only, with
   no added C#, .NET, or other technology keywords, and opens the
   corresponding company-specific Indeed or JobStreet search. These are search
   links, not verified vacancies; each job board controls its search behavior.
   Searches use shortened names: directory markers and trailing legal text such
   as `PTY. LTD. Philippines - ROHQ *` are omitted, and Indeed queries are not
   forced into exact-name quotes. The original directory identity is preserved.
   If a search is still too restrictive, open **Adjust a company's search name**,
   choose the company, edit **Job-board search name**, and save. The saved search
   name applies to both boards, CSV exports, and future provider searches; it
   never approves a different employer as the same partner. Job boards may show
   broader fallback results, so verify the employer on each specific posting.
4. **Download all partner search links (CSV)** exports the complete loaded list
   with company-name searches on both boards, even if the table is filtered.

The connected personal sheet was loaded into the private local matcher snapshot
during setup. Use the load controls to refresh it or switch tabs. Your personal
copy does not automatically follow updates in the school's original Excel file.

### Automatic posting discovery (optional provider key)

The **Discovered postings** tab searches the web index for specific Indeed and
JobStreet posting pages. It does not connect to your personal job-board accounts.
Indeed/SEEK partner APIs are not used for unrestricted job-board searches.

To enable discovery, obtain a key from the
[Brave Search API dashboard](https://api-dashboard.search.brave.com/). Review the
provider's current plans and costs yourself before activating access. Add this
to your local ignored `.env`, then refresh the page:

```dotenv
BRAVE_SEARCH_API_KEY='your-key-here'
```

The key is read on rerun and never displayed. Search-link generation works without
it. No provider account, paid plan, or API key is created automatically.
API reference: [Brave Web Search](https://api-dashboard.search.brave.com/documentation/services/web-search).

Choose up to **10 companies per batch**, or use **Discover next N unsearched
companies** (default 3). Each company uses one provider request and up to 10
results. Requests are spaced 1.1 seconds apart; failures and rate limits stop the
batch without automatic retries. Successful company searches are saved as they
complete, so the next batch can resume. A changed location requires a new search.
Only company names, C#/.NET search terms, and the location are sent to Brave.
CVs, HR contact information, and application email content are not sent.

Only specific Indeed `viewjob` pages and JobStreet `/job/ID` pages qualify as
posting leads. Search pages and unsupported domains are discarded; tracking
parameters are removed. Classification uses titles and search snippets, not a
verified live vacancy or a complete company technology stack. In particular:

- Internship/OJT leads are prioritized using the posting title.
- Explicit C# mentions are distinguished from .NET-related roles with C# unconfirmed.
- A full-time developer opening is a hiring signal, not an internship offer.
- A company query returning a result does not prove that employer is the FEU partner.
- No indexed result means **no candidate found by that search**, not **no jobs exist**.

Use **Opportunity focus → Reviewed C# internships** to see only postings you have
reviewed as matching the employer, internship type, and C# language requirement.
Before saving a review, open the source, enter the employer shown on the posting,
choose role/language evidence, and check the acknowledgement. Related companies
cannot be confirmed as exact partner matches. Mark stale/closed ads **unavailable**
or unrelated results **rejected**. This records a review timestamp; it does not
automatically apply to or import that company into the mail queue.

Data is saved atomically in ignored `.local/partner-jobs.json`. Repeated searches
retain manual reviews/rejections. Switching directory versions archives the old
results; loading that version again restores its research. Matcher mutations
have independent write locks and stale-review checks. Source snapshots and search
results are private local app state, not additions to the public repository.
