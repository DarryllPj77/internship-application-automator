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

Below the matcher table, a filtered partner picker and Add to Target Companies
action load current POCs into an inline review form. Contacts are selected before
the form so their details can be populated reliably. Source names remain fixed;
recipient details and applicant skills are editable. Saving gives a Pending
target and updates the email preview without selecting a recipient for a batch.
Missing addresses and duplicate queue recipients get explicit feedback.

Company creation and matcher target review share a resume-skill multiselect,
requirements text area, explicit subset-matching action, and editable final
wording. No skills are preselected. These entry controls use persistent widget
keys instead of batched forms so selection callbacks can update the skills text
without dropping typed recipient details. CV skill suggestions remain independent
of the email attachment choice. The existing mint theme applies throughout.

A Find company job requirements expander is available for the matcher's selected
partner and both skill-entry paths. A role/location/source search leads to a
specific posting, source evidence, editable requirement text, and an explicit
review action. Search excerpts are visually distinct from full posting sections;
missing API access is visible beside a disabled search button. Reviewed sources
flow into the CV-skill intersection without claiming every resume skill is needed.

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
