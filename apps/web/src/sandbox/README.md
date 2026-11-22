# Web sandbox

A spike exists to make a design question answerable by looking at it, and to be deleted.

- Keep the question in `catalog.ts` and record its answer in the owning issue or domain docs.
- Put fixture data in `fixtures/` and authored graphs in `fixtures/graphs/`. Capture registry data from the API when the fixture needs operator specs.
- Render through product components and adapters. Keep feature imports pointing from the sandbox into the app.
- Put render options in the URL. Keep experiments read-only against live Workspace data.
- Keep routing stress cases in automated tests. Remove a spike when its question is answered.

The sandbox is available in development at `/sandbox`. Use `just lab-web` to
start it with a stand-in session. See the [Canvas lab reference](../../../../docs/agents/web-canvas.md).
