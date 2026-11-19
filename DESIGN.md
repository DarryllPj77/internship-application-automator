Software: local internship application workspace for Darryll Pajaganas.

The supplied mint/emerald palette, Inter and JetBrains Mono pairing, compact app
layout, exact status colors, and 150ms interactions define this refactor. They
override the design skill's marketing-page palette dealing, full-screen sections,
decorative effects, and invented contact restrictions. Existing applicant details,
CV selection, company data, and template content are retained.

The workspace has four functional regions: connection/CV/mode configuration;
editable company queue; template and exact email preview; confirmed batch execution
and activity. A collapsible Company sources & opportunities workspace sits above
the queue: directory source, column mapping, editable contact review, and a separate
posting research tab. Import and research actions never send mail. Labels distinguish
the POC's job title from an internship opening and technology mentions from applicant
skills. Source links, row numbers, checked dates, and manual review remain visible.

A separate FEU Partner Job Matcher expander gives the full directory a searchable
link table and CSV export without requiring HR-email imports. Three tabs separate
directory/search links, discovered posting leads, and provider setup. Snippet
classifications remain distinct from reviewed role/language fields, and exact
employer review avoids treating related subsidiaries as the same partner. The
existing mint surfaces, forest headings, restrained buttons, and focus rings apply.

Equal outer edges, pale mint panels, 8px corners, 20-24px card padding, 16-24px grid gaps, and
hairline borders establish the hierarchy. Status counts use tabular mono figures.
The current palette uses Soft Mint Green (#D1FAE5) for the canvas,
Crisp Pale Mint (#ECFDF5) for cards and modals, and #A7F3D0 borders. Inputs,
variable chips, dropdown menus, table headers, logs, and email previews use
Frost White-Mint (#F4FBF8). Headings and primary text use #064E3B; metadata uses
Muted Sage Slate (#374151). There are no pure-white surfaces in the custom UI/theme.
The primary accent is #059669 (#047857 on hover). Selected rows use #A7F3D0 at
60% opacity with a 2px emerald edge. Primary labels use #0F172A at rest and light
frost on the darker hover fill for readable contrast. Disabled primary actions
use the canvas/metadata/border tokens at full
opacity. Each KPI carries the same status pill as its company rows. Section
kickers use uppercase Inter, 11px, 600 weight and .06em tracking.
Company rows show real application states in bordered tinted pills. Search and
pagination keep larger queues scannable without dropping off-page selections.

Voice: concise application-workspace labels; explicit mail outcomes; no promotional
claims. Motion: 150ms color changes clarify hover, emerald selection identifies batch
targets, press scaling confirms a click, and visible focus rings support keyboard
navigation. Reduced-motion preferences remove transitions and transforms. No
scroll-driven or decorative animations are appropriate for this working dashboard.

The app remains Streamlit. A local HTML component replaces the canvas table because
canvas cells cannot provide native CSS pills, row borders, or accessible editable
inputs. All company edits still pass the existing Python model and atomic store;
the component cannot send mail. Preview, confirmation, and MCP guardrails remain
Python-controlled.
