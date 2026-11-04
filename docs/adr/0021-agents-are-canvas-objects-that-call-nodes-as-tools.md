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

### What an Agent can use is what is wired to it

- **Context:** cards, Library items and node outputs connected to the Agent, read as
  references, never copied.
- **Tools:** a node or call node connected through its tool handle. Its open inputs are
  the parameters the model fills or are hidden; inputs wired from upstream stay fixed.
  Its outputs are returned to the model or not.

### A tool call is a computation with no instance

A tool call builds a temporary copy of the tool node's instance with the model's
arguments as origins, fingerprints it, and submits it to the Project's scheduler with
no instances to record. It is cached and single-flight with canvas Runs and shares the
Project's concurrency budget, and it never moves an instance pointer, so a node keeps
showing its own result. Argument artifacts are deduplicated by content so identical
calls share a fingerprint. The tool call records the fingerprints and Run it used.

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
  executes it through the kernel, and the run resumes with the result.

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
- When result-store garbage collection arrives, conversations are retention roots.
- Agents calling Agents, sharing conversations outside the Workspace, and Agents
  editing the canvas are out of scope.
