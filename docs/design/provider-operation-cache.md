# Provider-operation cache

Some work Grafy does is paid for twice: the same crop of the same scan sent to
the same provider because a user moved a selection by four pixels, or the calls a
cancelled run had already completed being paid for again on the next run.
`grafy_core.provider_cache` keeps a Workspace's answers to provider requests and
hands them back when the request is genuinely the same one.

This document records what may be cached, what a key has to contain, and what the
cache promises across processes. The mechanism is in
`libs/core/src/grafy_core/provider_cache.py`; its only storage is the
`provider_operations` table.

## What this is not

The kernel **result store** (ADR 0020) maps a node *fingerprint* to the outputs of
that instance, and the canvas derives freshness from it. This cache is below a
node, and the two are not interchangeable:

| | Result store | Provider-operation cache |
| --- | --- | --- |
| Key | node fingerprint: operator, config, implementation identity, upstream digests | Workspace, operation identity, one request |
| Unit | one node computation's outputs | one provider call's answer |
| Reads | the scheduler, to decide what a Run must still do | the wrapped operation, on its way to the provider |
| Lifetime | as long as the graph may refer to it | until its ttl passes, then swept |
| Holds failures | never; they go on the instance pointer | never; nothing is written |
| Visible to the canvas | yes, it is what freshness means | no |

A lazy operation is the reason the second one exists at all. A TIFF window that
reads its bytes when it is asked for them has no node instance and no
fingerprint — there is nothing in the result store to consult, and one node
computation may issue many provider calls, each worth keeping on its own.

**Providers stay cache-unaware.** The cache wraps a callable at composition time;
the node, the reader object, and the SDK call behind it keep their signatures and
see nothing. That is the whole reason the wrapper is a function that returns a
function rather than a mixin, a base class, or a decorator on the provider's own
methods.

## Opt-in, and what a caller must be able to say

Nothing is cached that did not ask to be. `cached_call` is applied where a provider
binding is built and the Workspace is known; `ProviderCache.get_or_compute` is
called directly by an operation whose work is a closure rather than a signature.
A caller that cannot state the following three things honestly does not get a
cache:

**Operation identity** (`CacheSpec`) — `operation`, `deployment`, `revision`,
`schema_version`. `revision` is the immutable implementation or model revision:
the digest of the code that builds the request and reads the response, or the
model id the provider names in its answer. It must move whenever the answer could
change for the same request. The cache cannot detect a revision that failed to
move, so this is the caller's one unenforceable duty and the reason a binding
without a stable revision passes.

`schema_version` belongs to the codec, not to the provider: changing the encoded
shape of the answer retires the old entries as misses rather than having them
decoded into something new.

**Request identity** — canonical JSON of every output-affecting setting plus a
digest of the input bytes. Bytes go in digested, and never raw: the key describes
the work, it does not carry it. Credentials never go in: a key that held a
credential would be a key that leaked it, and rotating a key would look like a
change of question. Untrusted or descriptive metadata — a node title, a file name
shown in the panel, a graph id — stays out too, because two different documents
can legitimately produce the same question and should share the answer.

A request value that is not JSON is refused with the path that failed rather than
coerced: a value `json.dumps` cannot name has no stable digest, and guessing one
is how two different requests end up sharing one answer. Bytes, `SecretStr`, sets
(unordered), NaN and infinities, and arbitrary objects are the refusals a caller
meets in practice.

**Workspace** — supplied by Grafy, never read out of the request. It leads the
stored primary key and is a foreign key to `workspaces`, so the partition is a
storage fact: two Workspaces behind one provider credential cannot read each
other's answers, and deleting a Workspace takes its answers with it.

## Guarantees

- **A hit is decoded before it is trusted.** A payload the spec's codec refuses is
  retired and the operation runs, so an entry written by an older build costs one
  recomputation instead of becoming a node failure.
- **An empty answer is an answer.** A JSON `null` and an empty result are stored
  and served like any other; re-asking a provider about a crop with no text in it
  is exactly the cost this exists to remove.
- **Each successful call is written immediately.** A run interrupted after twelve
  of twenty crops has those twelve answers for the run after it.
- **Failures and cancellation write nothing** and poison nothing: a key that failed
  is retried on the next call, and the transient provider outage that started as
  one failed run does not become a permanent one.
- **Concurrent misses in one API process make one provider call**, coalesced per
  `(workspace, key)`. The coalescing entry exists only while a call holds it — it is
  reference-counted and released in a `finally`, so a cancelled attempt cannot leave
  a lock behind and the map is bounded by concurrency, not by history.
- **No cache transaction is open while a provider is being waited on.** The SQL
  store takes a session factory, not a session, and each of its operations is a
  transaction of its own. That is also why it is not a repository on the unit of
  work: the unit of work of a node computation spans materializing inputs and
  minutes of provider latency, and a cache read pulled into it would hold that
  transaction open across the call and block the write that has to land the moment
  the answer arrives.
- **Cache faults stop at the store boundary.** A read failure is a miss; a write
  failure costs the entry and not the answer. Provider exceptions and task
  cancellation propagate untouched — the `except Exception` around a cache call is
  the only place this module swallows anything, and it never wraps `compute`.
- **Progress later.** The boolean from `get_or_compute`, and `observe_hit` on
  `cached_call`, say whether this call skipped the provider. Nothing in the web
  reads it yet; a per-item "from cache" marker is a UI change on top of this.

### What the boolean means

`True` means *this caller did not run its own work*: either a stored entry served
it, or it waited on another call in the same process that served the first. A caller
that ran its work and then found the key already held another process's answer gets
`False` and that stored answer — it paid, and the persisted bytes are what it
returns.

### Cross-process behaviour, stated plainly

There is no cross-process call graph. Two API processes that miss on the same key
both call their provider, and atomic storage makes the outcome one complete row
rather than a torn one: the insert decides existence and expiry in one statement
(`INSERT … ON CONFLICT DO UPDATE … WHERE expires_at <= now`), the winner is read
back in the same transaction, and a loser is handed the bytes that persisted.
Distributed single-flight is out of scope, deliberately — Grafy runs one API
owner for collaboration already (`single_owner.py`), and a second process missing
on a key costs one duplicate provider call, not correctness.

## Storage, expiry, and reclamation

One row per answer: `(workspace_id, key_sha256)` primary key, `payload`,
`stored_at`, `expires_at`, plus `ix_provider_operations_expires_at`.

Rows are bounded by time rather than by count. `get` compares `expires_at` in the
statement, so expiry ends an entry's visibility the moment it passes and a row a
sweep has not reached is invisible, not wrong. Reclamation is
`delete_expired(now, limit)`: a bounded batch (`DELETE … WHERE (workspace_id,
key_sha256) IN (SELECT … LIMIT n)`, since PostgreSQL has no `DELETE … LIMIT`),
called by the cache at most once per interval per process, after a write and
outside the coalescing gate. A deployment that never sweeps keeps dead bytes rather
than wrong answers; the sweep cadence and batch size are settings, and
`ProviderCache.cleanup_expired()` runs one on demand. Capacity is bounded twice
over: rows stop being served at their ttl, and an answer larger than
`provider_cache_max_payload_bytes` is not stored at all — the operation still
returns it, it just is not reusable.

Retiring an entry uses the same door: `put` with a zero ttl stores a row that has
already expired, which is how the codec-refused path gives up its space without a
delete of its own, and why the table check is `expires_at >= stored_at`.

The cache holds provider answers, not user artifacts, so it is not part of graph
retention: it never holds a reference an artifact deletion has to respect, and it is
safe to truncate by hand when a deployment wants the space back immediately.

## Configuration

`ProviderCacheConfig` (`GRAFY_PROVIDER_CACHE_*`), composed into `Settings`:
enabled, ttl, sweep interval, sweep batch rows, maximum payload. Nothing here turns
caching on for an operation that did not ask for it — `provider_cache_enabled=false`
only removes the store a binding would otherwise be handed.

## Wiring a provider operation

The shape at a binding is:

```python
spec = CacheSpec(
    operation="tiff.window_boxes",
    deployment="fake.detection@1",
    revision=DETECTION_REVISION,           # moves when the answer could move
    schema_version=1,                      # moves when the encoded shape moves
    codec=TypeAdapter(list[Box]),
    ttl_seconds=settings.provider_cache.provider_cache_ttl_seconds,
)
detect_window = cached_call(
    detect_window,
    cache=cache,
    workspace=context.workspace_id,
    spec=spec,
    identify=window_identity,              # total over the arguments
)
```

`identify` must name everything the work reads. A setting it omits is a setting two
calls will disagree about while sharing one entry, and the second one silently gets
the first one's answer — the failure mode a cache cannot undo afterwards.

### For the TIFF window and CRAFT detection nodes

What is coming from the TIFF branch is a node that asks what text-bearing regions
sit under a window of a page, reading the page lazily. The key it needs:

```python
{
    "source_sha256": page.source_sha256,   # content digest, not the artifact id
    "page": page.page,
    "window": [col, row, width, height],   # page-anchored tile, see below
    "png": "window-png@1",                 # bump when the read or encode changes
    "detect": {"core_edge": 600, "context": 200},
}
```

- **Use the content digest, not the artifact id.** A re-upload of the same bytes
  under a new id is the same question, and a new id is also what a corrected upload
  of a *different* scan looks like.
- **Name the preprocessing version.** Downscaling, greying, contrast and any
  rotation applied before the provider sees the window all change the answer without
  appearing anywhere else in the request. One string, bumped when the transform
  changes, and the whole family of old window answers retires at once.
- **`detect` holds what is actually sent**, taken from the resolved config after
  defaults — not the node's raw config dictionary, which can carry a field the
  request never reads.

**Anchor the scan grid to the page, not to the selection.** If `bounds` are the
pixels the user drew, every pointer move is a new provider call, which is the cost
this cache cannot recover. The fix is that the *identity and the work* name a
tile-aligned rectangle derived from the page origin:

```python
tile = Tile(
    x0=(x0 // TILE) * TILE,
    y0=(y0 // TILE) * TILE,
    x1=ceil(x1 / TILE) * TILE,
    y1=ceil(y1 / TILE) * TILE,
)
```

Then a selection that stays inside its tiles reuses the answer, a selection that
grows into the next tile costs one new call, and dragging a box across a page costs
the tiles it crossed rather than a call per pointer event. Two rules make that work,
and they are the ones to hold in the node:

1. **The operation reads exactly what the key names.** A key over the tile with a
   read of the raw selection serves one rectangle's boxes for another's, and no
   later change can undo that. The node asks for the tile and filters the returned
   boxes to its own selection afterwards — filtering is free, a wrong answer is not.
2. **The grid is page-anchored and its size is part of the identity.** Include the
   tile size in `detect` (or in the `preprocessing` version) so that changing the
   granularity retires the grid rather than mixing two granularities' answers under
   one key.

The lazy read then belongs *before* the bytes: wrap the operation that reads the
window and calls the provider, so a hit touches neither the file nor the network.
`ProviderCache.get_or_compute` exists for exactly that, since the work is a closure
over bytes not yet fetched rather than a callable with a signature.

### For polygon OCR

A polygon crop is already cut and normalised, so the request is the bytes that get
sent plus what the recognizer was told:

```python
{
    "crop_sha256": sha256(prepared_crop_bytes),   # exact bytes after preprocessing
    "recognizer": <model id>,
    "preprocessing": "label-crop@1",
    "options": {},                                # what the recognizer was actually sent
}
```

The node looks up a group of prepared crops together. Stored crops come back from
the cache. The misses go to the recognizer in one call, and each answer is stored
under its own key. A repeated crop is one of those keys, so it does not add a second
provider call. The model id is the spec's revision, and the request names it as well
so two recognizers cannot share one answer.

Digest the prepared bytes, not the source region: two polygons on two different pages
of two different files that cut to identical pixels are the same call, and that is a
feature. The recognizer never saw the file. The digest must be of the bytes sent,
taken after any resize or normalisation, or the key will claim reuse for two requests
whose pixels differ.

### Progress and logs

`observe_hit` is where a per-item marker lands when the canvas wants one. It is
called once per operation with whether the work was skipped, from the operation's own
task, so a progress reporter can attribute it to the running item. Nothing in the web
reads it today and nothing will change until someone decides what a cache hit is
worth showing.

At `DEBUG`, `grafy_core.provider_cache` says which way each call went:

```
provider_cache_miss workspace=<uuid> operation=tiff.window_boxes key=<sha256>
provider_cache_hit  workspace=<uuid> operation=tiff.window_boxes key=<sha256> coalesced=false
```

`coalesced=true` marks the caller that waited on another call's provider request
rather than reading a stored row — the two are one boolean to the caller because the
answer they got is the same, and the log is where the difference is still there.
Faults are logged at `WARNING` (`provider_cache_read_failed`,
`provider_cache_write_failed`, `provider_cache_payload_unreadable`,
`provider_cache_cleanup_failed`), which is what a deployment without `DEBUG` sees,
and those lines are enough to tell a cache that is off from one that is silently
failing.

The key is a digest and the request never enters a log line. That is deliberate: a
request names a document, a page and a rectangle, and a node's own progress message
is the place an operator who is allowed to see that graph can read it. A hit counter
belongs in the node's progress line (`report_progress`) for the same reason — the
cache has no business naming what it was asked about.

## Deliberately out of scope

- Distributed single-flight, and any cache-coherent broadcast between processes.
- Caching anything that is not a provider answer: node outputs belong to the result
  store, rendered tiles to the tiler's own bounded cache.
- A universal decorator over every provider method, and any cache that a node can
  enter by configuration alone. Each entry is a named operation with a named
  revision, or it is not cached.
- Invalidation UI. Expiry, a bumped revision, and a bumped schema version are the
  three doors out; `provider_cache_enabled=false` is the fourth.
- Result-store garbage collection, which ADR 0020 still lists as required before
  production and which is a separate decision.
