## 2026-11-28 — shared status overview

- Status counters now appear in the shared sticky header across workspace sections. The read-only overview opens a numbered company table by status and displays recorded failure reasons. This supersedes the queue-only counter visibility described below.
- Verification for this release uses the Python regression suite and Node table tests. Previous visual-gate findings below remain documented; this dependency release does not claim a new design-gate pass.

## 2026-11-23 — feature sidebar and retained queue view

- Replaced the vertically stacked feature panels with left-side navigation: Company queue, Compose & preview, Check manually sent drafts, Queue skills, Add company, Bulk import, Company sources, Partner job matcher, Gmail/CV/recipients, Batch activity, and failed-operation review.
- Inactive feature panels remain mounted but hidden as normal navigation views. This preserves Streamlit widget inputs, resume choices, and selected company IDs while switching views. No Gmail request is made by navigation itself.
- Queue search, status filter, page, and page size are retained in this browser tab's session storage across component reloads. Storage errors fall back gracefully. Actual company statuses remain persisted through the existing store.
- Retained the mint palette, hairline borders, and form controls. Sidebar starts collapsed on narrow screens; use the upper-left sidebar control to open it. Queue metrics are hidden outside the queue view to keep tools compact.
- Verification: 104 Python tests and 14 Node table tests passed, including frame recreation, rapid selections, and cycling every feature without losing unfinished forms or queue statuses. No emails were sent during this verification.
- Browser review: inspected desktop queue at 1440px and phone navigation/tool entry at 390px. Captures are under ignored `.taste-skill/shots/sidebar-*`.
- Design gate: **GATE: FAIL 19 (round 2 of 3)**. The automated landing-page/Streamlit checks did not pass; this is not a full design-gate approval. Open categories: container-edges, cta, focus-ring, focus-visible, heading-scale, hero-screen, moment-none, one-heading, one-section. Findings include hero/CTA rules, metric-heading scale, framework focus rules, phone target size, and container-edge rules. The separate layout checker also reported no Chrome found, while the screenshot and consistency tools did run. No waivers were added and no kit files were edited.

# Company requirements search (2026-11-20)

Added role/location/source search for selected partners and company-entry skills
pickers using the existing search API adapter. Specific JobStreet/LinkedIn/Indeed
posting links and public career pages are presented as candidates. Excerpts,
structured qualifications, extracted sections, and manual text remain distinct.
The user reviews employer and requirements before applying a source. Public
career-page reading uses existing network safeguards; job-board account pages
are not fetched. Applied sources fill requirements and intersect detected CV
skills, preserving manual edits and clearing old automatic context on a company
change. Source records are private local state.

Verification: all 92 Python tests and 10 Node table tests passed, including source
classification, multi-job rejection, optional-block extraction, company review,
skills application, company switches, and matcher-to-target handoff. Search API
calls were mocked because no live key is configured; no live search or new queue
entry was represented as completed. Desktop/mobile entry renders were checked
separately. The existing marketing-page gate results below remain historical.

---

# Resume skill picker (2026-11-20)

Added the same CV skills dropdown, optional required-text matcher, and editable
final skills field to Add company and matcher target review. Suggestions come
from local PDF text, preferring declared skill sections and excluding obvious
Currently Learning entries. Initial selection is empty. Matching intersects CV
skills with supplied requirements; company names are not treated as requirement
evidence. The final wording remains editable. Typed company/recipient values are
preserved across selection callbacks. Skills CV selection does not alter the
email attachment.

Verification: 81 Python tests and 10 Node table tests passed, covering local PDF
extraction, optional requirements, subset selection, manual edits, and contact
preservation in both entry paths. An existing uploaded CV was parsed locally;
no live queue entry was added during verification. Browser renders were checked
separately. Earlier marketing-page gate results below remain historical.

---

# Partner-to-target workflow (2026-11-20)

The matcher table now leads into a filtered partner picker and Add to Target
Companies action. The action fetches current worksheet rows, checks the company
identity rather than relying on stale row numbers, and detects multiple POC
header groups. A separate inline form reviews recipient, contact title, and
applicant skills before a Pending row is saved through CompanyStore. Cancel and
invalid addresses leave the queue unchanged. Duplicate addresses preserve existing
edits, Sent status, results, and recovery state. Existing batch/concurrency locks
apply; the queue and preview refresh after a save without selecting mail targets.
Filtered tables shrink to expose the action below short result sets.

Verification: all 72 Python tests and 10 Node table tests passed, including POC
selection, missing-email correction, cancellation, duplicates, moved source rows,
and batch-lock behavior. Live Indra Philippines lookup found a POC at row 512
with no valid email; no real target was added during verification. The local app
was restarted. Browser entry renders were checked separately from the isolated
UI tests; previous marketing-page gate results below remain historical.

---

# Job-board search-name correction (2026-11-19)

Search links now omit directory markers and terminal legal text, and Indeed no
longer forces the full legal employer name into exact-name quotes. The directory
table exposes the shorter search name. A saved per-company search-name editor
applies to both job boards, exports, and provider queries while preserving the
directory identity and strict employer-review checks. BCS Technology PTY. LTD.
Philippines - ROHQ * now searches as BCS Technology. Broad result counts are not
treated as matched-company vacancy counts.

Verification: all 64 Python tests passed, including BCS query cleanup, custom
search-name persistence, and preservation of distinct employer identities. The
running app was restarted and its updated desktop render inspected.

---

# FEU partner job matcher (2026-11-19)

Added a separate matcher workspace with directory/search-link, discovered-posting,
and setup tabs. Search links and the full CSV export remain available without a
provider key. Posting leads distinguish title/snippet evidence from manually
reviewed employer, role type, language, and availability. Related subsidiaries
cannot be confirmed as exact partner matches. The email queue is independent.

Live setup read 1,300 company rows from the connected GENERAL MASTERLIST and
stored 1,286 normalized unique names locally, including partners without email
addresses. Exported all 5,144 C#/.NET search links. A real discovery request was
not run because no Brave Search API key is configured. Provider behavior and
review flows were exercised with mocked search responses, not presented as live
job-board matches. The saved directory is the user's personal copy.

Verification: 62 Python tests and 10 Node table tests passed. Desktop (1440px)
and phone (390px) matcher entry renders were inspected. The marketing-page gate
was not rerun for this functional dashboard addition; earlier gate entries below
remain historical.

---

# Company sources and opportunity workspace (2026-11-19)

Added a collapsible source workspace above the company queue, retaining the mint
tokens and existing typography. Directory import uses explicit worksheet/column
mapping and an editable review table. Role research has a separate tab, source
links, checked dates, and a review action; applicant skills remain separate.
The queue summarizes saved role titles and exposes technology mentions on hover.

Verification: 52 Python tests and 10 Node table tests passed, including the full
review/import/save-posting UI path, existing mail/queue checks, and a real stdio
MCP handshake. Desktop (1440px) and phone (390px) entry renders were inspected.
Live Google consent completed and its token was saved. The supplied original
directory returned Sheets HTTP 400 because it is an Office workbook; reading it
requires a Drive reader or a native Google Sheets copy. This is separate from the
offline suite. The existing marketing-page gate findings below are historical;
that gate was not rerun for this functional dashboard addition.

---

# Latest surface update: Mint Green (2026-11-19)

Current tokens supersede historical palettes below: #D1FAE5 canvas,
#ECFDF5 panels/modals, #F4FBF8 nested fields/table headers/email previews,
#A7F3D0 borders, #064E3B primary text, and #374151 metadata.
Actions use #059669 with #047857 hover; selected rows use 60% seafoam tint
and a 2px emerald edge. Error and destructive actions retain rose semantics.

Verification: inspected desktop (1440px) and phone (390px) screenshots;
10 Node table tests passed. Of 36 Python tests, 35 passed; the existing
dashboard-preview test assumes live sample companies, but companies.json is
currently empty, so it cannot find its selector. User data was not changed.
Whitespace checks passed. The broader marketing-page gate was not rerun for
this scoped token update; earlier results below remain historical.

---

# Latest surface update: stepped gray-on-gray (2026-11-18)

Current tokens supersede historical palettes below: #CBD5E1 canvas,
#E2E8F0 cards/modals, #F1F5F9 nested inputs/previews, #94A3B8 borders,
#0F172A primary text, and #334155 metadata. Corporate Cobalt actions remain.
Primary button labels use the frost token to retain contrast without pure white.

Verification: 21 Python and 5 Node table tests passed; whitespace checks passed;
the updated desktop render was inspected. No pure-white definitions remain in
the app theme or custom UI styles. The broader marketing-page gate was not rerun
for this surface-token update; earlier gate results below are historical.

---

# Latest surface update: Crisp Slate (2026-11-18)

The latest requested surfaces supersede the history below: #F8FAFC canvas,
#FFFFFF cards/modals, #F1F5F9 inputs/variable chips/table headers/previews,
and #E2E8F0 borders. No replacement accent value was specified, so Corporate
Cobalt actions, existing status colors, and selected-row behavior remain.

Verification: 21 Python and 5 Node table tests passed, whitespace checks passed,
and the updated desktop render was inspected. The broader marketing-page gate
was not rerun for this surface-token update. Older gate results below are historical.

---

# Latest color follow-up: layered cool slate (2026-11-18)

Current colors supersede the historical palette below: #E2E8F0 canvas,
#F1F5F9 panels/modals, #F8FAFC nested fields/table headers/email previews,
#DBEAFE selected rows, #CBD5E1 borders, and unchanged #2563EB/#1D4ED8 actions.
No pure-white surface definitions remain in the app theme or custom UI styles.
Table checkboxes use explicit mist/cobalt styling rather than native white fills.

Verification: 21 Python tests and 5 Node table tests passed. Inspected desktop
and phone renders. Mail behavior was not changed. This targeted token update did
not rerun the broader marketing-page gate; the gate results below are historical.

---

GATE: FAIL 22 (Corporate Cobalt styling review, 2026-11-18)

# Executive Tech & Corporate styling review

Applied the exact requested canvas, cobalt/royal accents, ice-blue selection, crisp slate borders, disabled CTA colors, and semantic status palettes to both the Streamlit dashboard and the embedded table. KPI cards now include their matching status pills. Kickers use uppercase Inter, 11px, 600 weight, .06em tracking. KPI digits explicitly use Obsidian Ink. Focus rings use cobalt at 25% opacity. Existing mail, template, recipient, and batch behaviors were preserved.

Verification: 21 Python tests and 5 Node table tests passed. Whitespace checks passed. Inspected final 1440px desktop and 390px phone renders; the desktop capture includes the gray zero-selection CTA. Browser captures and raw checker reports remain in ignored `.taste-skill/`. No emails were sent during verification.

The gate reports 22 FAIL and 32 WARN findings. There are no waivers. Several requirements intentionally differ from its marketing-page rules: this is a working multi-panel application, the exact muted token measures 6.92:1 against the requested canvas (the checker requires 7:1 for text it classifies as body), real template-variable controls contain the word placeholder, and the brief requires prominent KPI numerals and padded cards. The checker also flags nested Streamlit wrappers as clipped KPI rows; the inspected desktop capture shows all four complete cards and values. Streamlit chrome, `.wrap` conventions, and marketing hero/moment rules remain checker limitations. No universal gate or accessibility pass is claimed.

No new images, assumed facts, stand-ins, client asset slots, or decorative scenes were introduced. Local Inter and JetBrains Mono assets remain the font pairing. No new performance benchmark was run for this token-only styling update; earlier measurements below are historical, not new results.

## Current open FAIL findings

- **placeholder**: "placeholder" is a placeholder left on the page
- **copy-headings**: "Target companies" names no product, part, place or section (3 headings like it; at most one brand line per page) (and 2 more like it: "Compose & preview", "Batch activity")
- **copy-actions**: 6 actions in the hero ("Test MCP Connection", "Select all pending", "{contact_person}", "{company_name}", "{relevant_skills}", "Create Drafts for Selected (0)"); at most 2
- **heading-scale**: the figure "3" is set at 30px, larger than the section headings (h2 20px); 3 more like it
- **stagger**: 4 rows start at 3 different left offsets (+0, +21, +13, +0px)
- **text-contrast**: body text in #475569 on #f1f5f9 reads 6.92:1 (needs 7:1)
- **moment-none**: a software page (--type) deals no moment: every kind carries one, two on a long page (moments.md)
- **hero-screen**: the hero ends at 2328px on a 900px screen, 1428px below the fold: it ends at the fold, 1px either way (SR-1)
- **one-section**: a <div> sits directly in <main>: every part of <main> is a <section> (SR-4)
- **one-section**: a band: a box 94% of the section wide on a ground of its own that holds only text: the section's own ground is the band (SR-4)
- **one-section**: a band: a box 91% of the section wide on a ground of its own that holds only text: the section's own ground is the band (SR-4)
- **one-heading**: the hero holds an h2 (3): its heading is the h1, and an h2 opens the next section (SR-5)
- **container-edges**: the nav's content runs 1328px from the left and 18px from the right (read from its outermost blocks: no .wrap): the page's container starts at 40px; 1328 and 18px are not one margin; the margin is 64-120px at 1440px (one container, equal margins, 2px either way) (SR-6)
- **container-edges**: the content of section 1 runs 40px from the left and 40px from the right (read from its outermost blocks: no .wrap): the margin is 64-120px at 1440px (one container, equal margins, 2px either way) (SR-6)
- **container-edges**: "Main menu" runs 1394-1422px, outside the container lines of the nav at 40-1400px: full width is for background layers and grounds only (SR-6)
- **container-edges**: 6 text blocks start on a left line at x 82, 42px from the container's left: text starts on the container's left, or on one split line (x 617, 732, 847) (also "CC recipients (optional)", "CC recipients (optional)", "BCC recipients (optional)") (SR-6)
- **container-edges**: 3 text blocks start on a left line at x 65, 25px from the container's left: text starts on the container's left, or on one split line (x 617, 732, 847) (also "Disconnected", "Last discovery result. Each batc") (SR-6)
- **row-lines**: a row of 3 items: its first item starts at 65px, the container's left line at 40px; its last item ends at 1375px, the container's right line at 1400px (2px either way) (SR-7)
- **row-lines**: a row item is cut by a frame round it: 328 x 103px of its 328 x 126px shows (SR-7)
- **row-lines**: a row item is cut by a frame round it: 328 x 103px of its 328 x 126px shows (SR-7)
- **row-lines**: a row item is cut by a frame round it: 328 x 103px of its 328 x 126px shows (and 1 more like it: "FailedFailed0") (SR-7)
- **container**: no .wrap

## Current WARN categories

a11y-name, action-repeat, assumed, body-size, copy-buttons, copy-exclaim, copy-length, copy-stat-strip, field-label, focus-hidden, focus-ring, focus-visible, fold-action, form-fields, form-send, heading-order, img-alt, lang, map-link, menu-toggle, open-now, page-meta, photo-credit, progress-bar, run-on, share-meta, skip-link, stagger, tabindex, tap-size

---

The following is the historical review from the previous indigo styling pass.

GATE: FAIL 31 (round 1 of 3; cached Streamlit-shell result, not a current pass)

# Dashboard design verification

Functional verification: 17 Python tests and 5 Node table-behavior tests passed after the final patch. Git whitespace checks passed. Mail tests used an offline MCP fixture; no live Gmail delivery was attempted.

The skill was applied to a working Streamlit application. The user-specified indigo palette, local Inter/JetBrains Mono fonts, compact four-region layout, native editing, and 150ms interaction rules override the skill's marketing-page requirements for full-screen heroes, decorative visuals, arbitrary palette deals, and fictional contact data. No checker code was modified and no findings were waived.

Visual review: inspected desktop (1440px, full application) and phone (390px) screenshots. A fresh consistency run checked widths 1440, 1024, 768, and 390. It reported 32 FAIL and 46 WARN findings under its marketing-site rules. It passed color contrast, text contrast, font loading, overflow/spill, collision, button consistency, and empty-content checks. Its findings do not amount to a full accessibility certification. Some basic accessibility probes reported a CDP screenshot timeout.

The finish gate reused old results because Streamlit serves an unchanged HTML bootstrap while Python supplies the UI dynamically. The fresh report is more recent than the gate result. The final small spacing and font-configuration adjustments were followed by functional tests and a fresh browser performance run; the full consistency checker was not rerun after those two adjustments.

Performance: single-run local CPU samples at 1440 and 390; approximately 5 MiB transfer, 139-140 requests, and 4.2 MiB parsed JavaScript. The static-site budget reported 8 FAIL and 5 WARN findings (framework transfer, request, JS and font budgets; font family/file counts; desktop layout shift). LCP measured 596ms desktop / 820ms phone, blocking time 68ms / 67ms, CLS 0.165 / 0.094. No broken requests were reported. These are local single samples, not field measurements or a benchmark claim. Bundled Streamlit code and its Material Symbols icon font dominate the remaining payload. Converting the app to a different framework is outside this refactor.

Design: software workspace; exact client palette and font pairing; plain white panels with hairline borders, 8px corners and 20-24px padding. Voice: concise task labels and explicit email outcomes. Motion: hover, press and selection feedback only, with reduced-motion CSS. No assumed company facts, coined brands, stand-in images, client asset slots, shaders, or decorative scenes were introduced.

Generated screenshots, raw reports, and browser profiles live in ignored `.taste-skill/`. Font license texts are included in `static/fonts/`.

## Open consistency findings

All fresh-run FAILs and retained WARNs are listed below. Findings about a hero, a section taking a whole screen, photography, or marketing CTA counts do not match the requested working dashboard. Framework focus-rule, metadata, and tap-target warnings remain limitations to review; visible focus styling was added without altering Streamlit's distributed CSS.

### FAIL

- **placeholder** (1440px): "placeholder" is a placeholder left on the page
- **no-visual** (1440px): pictures, effects and mocks cover 8% of this section; a feature section needs a visual (about 25% or more)
- **copy-actions** (1440, 1024, 768, 390px): 6 actions in the hero ("Test MCP Connection", "Select all pending", "{contact_person}", "{company_name}", "{relevant_skills}", "Create Drafts for Selected (0)"); at most 2
- **heading-scale** (1440, 1024px): the figure "3" is set at 30px, larger than the section headings (h2 20px); 3 more like it
- **stagger** (1440, 1024, 768px): 4 rows start at 3 different left offsets (+0, +21, +13, +0px)
- **stagger** (1440, 768, 390px): 3 rows start at 3 different left offsets (+40, +21, +0px)
- **hero-screen** (1440px): the hero ends at 1706px on a 900px screen, 806px below the fold: it ends at the fold, 1px either way (SR-1)
- **one-section** (1440px): a <div> sits directly in <main>: every part of <main> is a <section> (SR-4)
- **one-section** (1440px): a band: a box 94% of the section wide on a ground of its own that holds only text: the section's own ground is the band (SR-4)
- **one-heading** (1440px): the hero holds an h2 (3): its heading is the h1, and an h2 opens the next section (SR-5)
- **container-edges** (1440px): the nav's content runs 1328px from the left and 18px from the right (read from its outermost blocks: no .wrap): the page's container starts at 40px; 1328 and 18px are not one margin; the margin is 64-120px at 1440px (one container, equal margins, 2px either way) (SR-6)
- **container-edges** (1440px): the content of section 1 runs 40px from the left and 40px from the right (read from its outermost blocks: no .wrap): the margin is 64-120px at 1440px (one container, equal margins, 2px either way) (SR-6)
- **container-edges** (1440px): the section needs exactly one in-flow child .wrap (it has 1 in-flow child, 0 .wrap) (SR-6)
- **container-edges** (1440px): "Main menu" runs 1394-1422px, outside the container lines of the nav at 40-1400px: full width is for background layers and grounds only (SR-6)
- **container-edges** (1440px): the h2 starts 834px right of the container's left: every h1 and h2 starts on it, 2px either way (SR-6)
- **container-edges** (1440px): 6 text blocks start on a left line at x 65, 25px from the container's left: text starts on the container's left, or on one split line (x 617, 732, 847) (also "Disconnected", "Last discovery result. Each batc", "01 / Company queue") (SR-6)
- **container-edges** (1440px): the h2 starts 25px right of the container's left: every h1 and h2 starts on it, 2px either way (SR-6)
- **row-lines** (1440px): a row of 3 items: its first item starts at 65px, the container's left line at 40px; its last item ends at 1375px, the container's right line at 1400px (2px either way) (SR-7)
- **split-pair** (1440px): the split's columns are off the page's one pair of lines: its left column ends at 817px, not 24px before the right one (823px) or a column before it (708px) (SR-8)
- **no-visual** (1024, 768, 390px): no picture, effect or mock in this section; a feature section needs a visual
- **heading-scale** (768px): the figure "3" is set at 30px, larger than the h1 (28px) (and 1 more like it: "0")
- **heading-scale** (390px): the figure "3" is set at 24px, larger than the section headings (h2 20px); 3 more like it

### WARN

- **copy-headings** (1440px): "Batch activity" names no product, part, place or section (the one brand line a page may have)
- **copy-buttons** (1440px): "Test MCP Connection" does not start with a verb (book, buy, try, start, get, see...) (and 3 more like it: "Select all pending", "{company_name}", "{relevant_skills}")
- **body-size** (1440px): 3 of 3 paragraphs of running text are set under 16px (13px)
- **photo-credit** (1440px): 1 library source (placehold): the page credits placehold; confirm each shows the client's own product, place or people
- **copy-length** (1440px): 1 section over 90 words a screen outside the UI mocks ("Internship applications" 105); 105 words a screen across the page (199 words in 1.9 screens): a tech page says it in about 80 or fewer
- **progress-bar** (1440px): a progress or meter bar on the page, like the one in "Ready when you are": the house rules have no drag or progress bars
- **fold-action** (1440px): the hero's second button "Create Drafts for Selected (0)" starts 554px below the first screen (900px tall): it is not seen on load
- **moment-none** (1440px): a software page (--type) deals no moment: every kind carries one, two on a long page (moments.md)
- **a11y-name** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **img-alt** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **field-label** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **heading-order** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **tabindex** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **focus-ring** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **focus-visible** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **focus-hidden** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **skip-link** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **menu-toggle** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **lang** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **page-meta** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **share-meta** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **action-repeat** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **map-link** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **open-now** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **assumed** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **run-on** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **form-fields** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **form-send** (1440px): partly measured: the basics block (CDP timeout: Page.captureScreenshot)
- **fold-action** (1024px): the hero's second button "Select all pending" starts 339px below the first screen (768px tall): it is not seen on load
- **fold-action** (1024px): the hero's second button "{contact_person}" starts 1142px below the first screen (768px tall): it is not seen on load
- **fold-action** (1024px): the hero's second button "{company_name}" starts 1142px below the first screen (768px tall): it is not seen on load
- **fold-action** (1024px): the hero's second button "{relevant_skills}" starts 1142px below the first screen (768px tall): it is not seen on load
- **fold-action** (1024px): the hero's second button "Create Drafts for Selected (0)" starts 1673px below the first screen (768px tall): it is not seen on load
- **hole** (768px): the card is 720px wide but its content keeps to the left 20%: the right side stands empty
- **fold-action** (768px): the hero's second button "Select all pending" starts 79px below the first screen (1024px tall): it is not seen on load
- **fold-action** (768px): the hero's second button "{contact_person}" starts 883px below the first screen (1024px tall): it is not seen on load
- **fold-action** (768px): the hero's second button "{company_name}" starts 883px below the first screen (1024px tall): it is not seen on load
- **fold-action** (768px): the hero's second button "{relevant_skills}" starts 883px below the first screen (1024px tall): it is not seen on load
- **fold-action** (768px): the hero's second button "Create Drafts for Selected (0)" starts 1414px below the first screen (1024px tall): it is not seen on load
- **tap-size** (390px): a 314x36px tap target: under the 44px a phone needs
- **fold-action** (390px): the hero's second button "Select all pending" starts 597px below the first screen (844px tall): it is not seen on load
- **fold-action** (390px): the hero's second button "{contact_person}" starts 1517px below the first screen (844px tall): it is not seen on load
- **fold-action** (390px): the hero's second button "{company_name}" starts 1577px below the first screen (844px tall): it is not seen on load
- **fold-action** (390px): the hero's second button "{relevant_skills}" starts 1637px below the first screen (844px tall): it is not seen on load
- **fold-action** (390px): the hero's second button "Create Drafts for Selected (0)" starts 2185px below the first screen (844px tall): it is not seen on load

## Scope

Changed presentation, documentation, and tests only. Existing changes to `companies.json`, `template.txt`, the installed `.agents/` skill, and `skills-lock.json` were not included in the proposed Git handoff. Gmail MCP and core batch/validation logic are unchanged.
