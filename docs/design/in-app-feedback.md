# In-app feedback

People report a problem or an idea from inside the app. They click **Send feedback**
in the rail, pick the element the report is about (or the whole page), and write a
message. Operators triage the reports at `/admin/feedback`. The vocabulary entry is
`FeedbackReport` in `CONTEXT.md`. This note records the decisions the code does not
make obvious.

## Reports stay in the deployment

A report is a row in `feedback_reports`, and its screenshot is an object at
`feedback/{report_id}.png|jpg` in the deployment bucket. Nothing is sent to GitHub by
the server. The grafY repository is public, and a report can hold research data,
names and screenshots of a Workspace, so publishing it is a person's decision:
**Draft GitHub issue** opens a prefilled new-issue form in the operator's browser.
The draft leaves out the reporter, the Workspace, and the slug and ids in the page
path. The operator still reads it over, because the message and the element label
can carry data, and they attach the screenshot by hand if it is safe to share. They
then paste the issue link back onto the report.

Reports are deployment-level, like `Operator`. The Workspace the page was in is
context for triage, and is accepted only when the reporter is an active member.
It grants nothing: operators carry no Workspace access, so the screenshot is often
the only view of the problem they get.

Every route takes a browser session only. MCP is a PAT-only adapter, and a PAT
never carries operator authority, so feedback has no MCP tools.

## Every way in has a way out

- Resolve and reopen. Reopening clears `resolved_at` and `resolved_by_user_id`.
- Link an issue and unlink it. `github_issue_url: null` clears the link, and an
  absent field leaves it alone.
- Delete removes the row and then the screenshot object. A failed insert deletes the
  object it had just saved.
- A deleted User or Workspace sets the reference to NULL and keeps the report.

## The picker and the screenshot

The picker is a transparent layer over the whole app, so the page underneath never
sees the pointer. `elementsFromPoint` looks through it to find the element, and
`meaningfulTarget` climbs from what was hit to what the person meant: a button
rather than its icon, or a canvas card (`data-card-id`) rather than a text run.

The screenshot is taken before the dialog opens, and the picker's own chrome carries
`data-feedback-ui`, so the image never shows Grafy's feedback UI. `modern-screenshot`
redraws the DOM rather than reading pixels from the screen. As a result, WebGL
canvases (MapLibre maps, some scan viewers) come out blank, and the dialog warns
when a canvas overlaps the crop. The browser's screen-capture API would capture
exact pixels, but it asks for permission every time. The crop is the element plus
48px around it, with the element outlined in the image. It is sent only when the
person leaves **Include screenshot** ticked.

Only the region around the pick is redrawn. Firefox took a minute to draw a whole
workbench page of about 10k elements, and the picker gave up, so the redraw starts
at the nearest clipping ancestor that can hold the crop (the canvas, for anything
on it). Out-of-flow elements that do not reach the crop, such as far-away cards,
are left out, which cannot move anything else. If the redraw still fails, one retry
leaves images, canvases and frames out. Large crops are drawn smaller and stepped
down to JPEG to stay under the upload limit.

The server accepts PNG or JPEG up to 2 MiB, checked by magic bytes, and at most 20
reports per person per hour.
