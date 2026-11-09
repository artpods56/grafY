# ADR 0021: Agents are canvas objects that call nodes as tools

- **Status:** Accepted
- **Amends:** ADR 0020 (a computation may run with no instance to record it)
- **Related:** epic #200 (#202 text chat, #203 node tools, #204 Graph tools),
  `CONTEXT.md` (Agent, Agent conversation, Agent tool link, Turn)

## Context

Historians need to ask questions of their sources and try models without building a
pipeline first. A chat does not fit the node contract: a node computes outputs from
inputs once, is cached by fingerprint and is fresh or stale. A conversation is
different on every turn, starts computations, waits for a person and can be
interrupted. Making it a node would turn every node rule into an exception.

## Decision

### An Agent is its own kind of canvas object

- An **Agent** sits on a Graph next to nodes and artifact cards and is neither. A Graph
  may hold several. Its setup (name, instructions, model, what is connected to it) is
  Graph document content, saved with checkpoints and copied with the Project.
- Expansion, fingerprints and Run planning ignore Agents and their links. An Agent is
  never an instance and is never scheduled. A link to an Agent never changes a node's
  fingerprint.
- **Conversations** belong to the Project, keyed by Agent, and are stored as
  append-only events: messages, tool calls, tool results, turn outcomes. Events are
  never edited; "continue from here" forks a new conversation from an event.
- Grafy's own event format is the durable record. The agent library's message format is
  rebuilt from events at the boundary and never stored.

### What an Agent can use is what is connected to it

- **Context:** node outputs, cards and Library items connected to the Agent, read as
  references, never copied. They are read fresh when a turn starts and told to the model
  after its instructions; a link that cannot be read is said to be unreadable, not dropped.
  A card or a Library item may vanish without the Agent refusing it; removing a node
  removes the links to it, as it removes the edges.
- **Tools:** a node connected as a tool, stored on the Agent as a tool link: a name the
  model sees, a description, the open inputs the model fills, and the outputs returned
  (none named means all). Inputs wired from upstream stay fixed. A model can only write
  text or integers, so only inputs of those types are offered; an input that makes a node
  fetch whatever address a model writes (Mistral OCR's `document_url`) is hidden unless a
  person offers it. A link the server cannot honour is reported as unavailable and not
  offered, rather than failing on its first call. A Library item link does not follow a
  copy into another Workspace.
- **Created artifacts:** every Agent can also call `create_artifact`, which no link names.
  Without sources it saves text the model wrote, such as an HTML document or a Markdown
  note, as a content-addressed text artifact a person can drag out of the conversation.
  With sources it saves an HTML page. The page is a Mustache template plus the artifacts
  it reads. The model names each source. The server stores the type and version it found.
  A page may name only artifacts connected to the Agent, or returned by a tool in this
  conversation. It points at those exact artifacts, so re-running a node does not change
  the page. The call starts no computation. A tool link with the same name takes its place.

### A tool call is a computation with no instance

A tool call builds a temporary copy of the tool node's instance with the model's
arguments as origins, fingerprints it, and submits it to the Project's scheduler with
no instances to record. It is cached and single-flight with canvas Runs and shares the
Project's concurrency budget, and it never moves an instance pointer, so a node keeps
showing its own result. The upstream computations the node's wired inputs need keep
theirs, because those results are what those nodes currently compute. The values a model
writes become inline artifacts whose id is derived from the Workspace, the type and the
content, so identical calls reach the kernel with identical origins and share a
fingerprint. The result event records the fingerprint it used.

### A turn runs on the server

- Send is an HTTP request, idempotent by a client-chosen turn id. One turn runs at a
  time per conversation. The API owner runs the turn; the reply streams to every
  participant over the Project room.
- Text deltas are coalesced, carry an offset, and are dropped rather than queued when a
  participant's room connection is busy. The stored message is authoritative and
  replaces the streamed text.
- Cancelling a turn withdraws its scheduler demand like cancelling a Run. On API
  restart running turns are marked interrupted; their events stay.
- The loop uses pydantic-ai with external tools: the run stops at a tool call, Grafy
  executes it through the kernel, and the run resumes with the result. What the model said
  before calling is stored as its own message ahead of its calls, the calls are stored
  before they run, and a call that fails or is given bad arguments is answered to the model
  as a failed result so it can try again. Cancelling withdraws a call in flight.
- A turn makes at most ten tool calls unprompted. The batch that would pass the limit is
  neither run nor stored; a `confirmation_requested` event stands in for it and the turn
  completes. The person's reply is an ordinary next turn that carries on from the results.
- The model is shown a result as text. A scalar shows its value. A JSON artifact shows
  compact JSON, cut off once it is longer than the view. A table shows a page of rows
  and the total, with column ids. A sequence shows its first items. A file that is not
  JSON gets a line saying its content is not shown. Each artifact is shown with its id,
  so the model can name it as a source. Images are described, not shown, until a
  multimodal view is decided.

### Models and permissions

- A deployment default model comes from operator configuration and may be a trusted
  private destination. Whoever configures an Agent may give it their own endpoint and
  key; that endpoint goes through the egress guard like an LLM node's `base_url`, the
  key is write-only, and everyone who can send to the Agent uses it.
- Reading conversations needs `view_project`. Sending needs `start_run`, because a turn
  runs computations. Placing and configuring an Agent, including its key, needs
  `edit_project`; unlike node secrets, an Agent's key does not need `manage_secrets`.

## Consequences

- The scheduler and result store need nothing new for tool calls; the runner needs a way
  to accept an instance that is not in the document.
- When result-store garbage collection arrives, conversations are retention roots. That
  keeps a page stored on a tool result. It does not keep an artifact named only inside
  that page.
- Agents calling Agents, sharing conversations outside the Workspace, and Agents
  editing the canvas are out of scope.
