# ADR 0013: Specialized file operators are published Plugins

- **Status:** Accepted
- **Amends:** ADR 0007
- **Related:** ADR 0008, ADR 0012

Decode images (`image.decode@1`) belongs to `external.image`. Import table
(`table.import@1`) belongs to `external.table`. Both are independently published,
isolated-only Plugins. Their operator identities, ports, and configuration stay
unchanged; saved nodes must change to `kind=plugin` with an exact release pin.
Neither release owns a new artifact type. Both depend on the deployment's exact
file and value contracts.

Normalize table text and Fuzzy match tables are removed. Collect, Count, Slice,
and Pick item are removed from the builtin catalog. The canvas Collect action
groups unconnected, homogeneous artifact cards into a sequence without adding an
execution node. It does not replace a Collect node fed by live graph edges.
Existing graphs with removed operators must be rebuilt; their documents and
historical revisions are retained rather than silently rewritten.

Text input, Integer, Schema Builder, Interpret file, and Module boundaries stay.
The four hidden text operators retained by ADR 0012 also stay. Image and Table
artifact contracts remain in the application so uploads, Library artifacts,
viewers, and Plugin dependencies continue to share the same types. The image
output writer moves with its only production producer into the image Plugin.
Table persistence remains in the application for table bundle import and paging.
Generic sequence fixtures live only under `tests/support` and use `test.sequence`
identities, so they cannot enter the production catalog.

## File bundle policy

Every builtin `file.*` contract declares `binary-file@1`. Stored upload bytes
cannot cross an isolated runtime through the default `inline-json@1` adapter.
New file-format contracts must declare the binary bundle explicitly, and
acceptance must run a file input through the Plugin guest, not only invoke the
node class directly. The builtin file-contract test enforces this policy for the
checked-in formats.

This corrects the old bundle declarations without rewriting stored artifact
references or immutable release manifests. A release carrying the old file
contract must be republished against the new SDK before it can join this catalog.
Deployment must retire its old selection before exposing the corrected contract.
Keep the old release, application image, and selection backup for rollback.
