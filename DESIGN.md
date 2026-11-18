Software: local internship application workspace for Darryll Pajaganas.

The supplied Corporate Cobalt/slate palette, Inter and JetBrains Mono pairing, compact app
layout, exact status colors, and 150ms interactions define this refactor. They
override the design skill's marketing-page palette dealing, full-screen sections,
decorative effects, and invented contact restrictions. Existing applicant details,
CV selection, company data, and template content are retained.

The workspace has four functional regions: connection/CV/mode configuration;
editable company queue; template and exact email preview; confirmed batch execution
and activity. Equal outer edges, white panels, 8px corners, 20-24px card padding, 16-24px grid gaps, and
hairline borders establish the hierarchy. Status counts use tabular mono figures.
The current surface palette uses Slate 50 (#F8FAFC) for the canvas and white
(#FFFFFF) for cards and modals, separated by Slate 200 (#E2E8F0) borders.
Inputs, variable chips, dropdown menus, table headers, logs, and email previews
use Slate 100 (#F1F5F9). The latest request specifies surface colors only;
the existing cobalt action colors remain until a replacement accent is supplied.
The primary accent is #2563EB (#1D4ED8 on hover). Selected rows use #DBEAFE
with a 2px cobalt edge. Disabled primary actions use #E2E8F0 and #64748B at full
opacity. Each KPI carries the same status pill as its company rows. Section
kickers use uppercase Inter, 11px, 600 weight and .06em tracking.
Company rows show real application states in bordered tinted pills. Search and
pagination keep larger queues scannable without dropping off-page selections.

Voice: concise application-workspace labels; explicit mail outcomes; no promotional
claims. Motion: 150ms color changes clarify hover, cobalt selection identifies batch
targets, press scaling confirms a click, and visible focus rings support keyboard
navigation. Reduced-motion preferences remove transitions and transforms. No
scroll-driven or decorative animations are appropriate for this working dashboard.

The app remains Streamlit. A local HTML component replaces the canvas table because
canvas cells cannot provide native CSS pills, row borders, or accessible editable
inputs. All company edits still pass the existing Python model and atomic store;
the component cannot send mail. Preview, confirmation, and MCP guardrails remain
Python-controlled.
