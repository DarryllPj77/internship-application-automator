Software: local internship application workspace for Darryll Pajaganas.

The supplied indigo/slate palette, Inter and JetBrains Mono pairing, compact app
layout, exact status colors, and 150ms interactions define this refactor. They
override the design skill's marketing-page palette dealing, full-screen sections,
decorative effects, and invented contact restrictions. Existing applicant details,
CV selection, company data, and template content are retained.

The workspace has four functional regions: connection/CV/mode configuration;
editable company queue; template and exact email preview; confirmed batch execution
and activity. Equal outer edges, white panels, 8px corners, 24px padding/gaps, and
hairline borders establish the hierarchy. Status counts use tabular mono figures.
Company rows show real application states in bordered tinted pills. Search and
pagination keep larger queues scannable without dropping off-page selections.

Voice: concise application-workspace labels; explicit mail outcomes; no promotional
claims. Motion: 150ms color changes clarify hover, indigo selection identifies batch
targets, press scaling confirms a click, and visible focus rings support keyboard
navigation. Reduced-motion preferences remove transitions and transforms. No
scroll-driven or decorative animations are appropriate for this working dashboard.

The app remains Streamlit. A local HTML component replaces the canvas table because
canvas cells cannot provide native CSS pills, row borders, or accessible editable
inputs. All company edits still pass the existing Python model and atomic store;
the component cannot send mail. Preview, confirmation, and MCP guardrails remain
Python-controlled.
