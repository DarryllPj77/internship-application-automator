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
