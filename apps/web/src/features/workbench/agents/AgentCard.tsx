"use client";
import * as React from "react";
import { NodeResizer, type Node, type NodeProps } from "@xyflow/react";
import type { SavedGraphAgent } from "@/lib/api/contract";
import { agentApi, type AgentScope } from "@/lib/api/agents";
import { useAgentChat } from "./useAgentChat";
export type AgentNode = Node<
  {
    remoteSelectionColor?: string | null;
    agent: SavedGraphAgent;
    scope: AgentScope | null;
    canEdit: boolean;
    canSend: boolean;
    configure: (agent: SavedGraphAgent) => void;
    remove: () => void;
  },
  "grafyAgent"
>;
function Conversation({
  scope,
  canSend,
}: {
  scope: AgentScope;
  canSend: boolean;
}) {
  const chat = useAgentChat(scope);
  const [text, setText] = React.useState("");
  return (
    <>
      <div className="nodrag nowheel">
        <select
          aria-label="Conversation"
          value={chat.conversationId}
          onChange={(event) => chat.select(event.target.value)}
          disabled={chat.busy}
        >
          <option value="">Choose a conversation</option>
          {chat.conversations.map((item, index) => (
            <option key={item.id} value={item.id}>
              {item.title || `Conversation ${index + 1}`}
            </option>
          ))}
        </select>
        {canSend && (
          <button onClick={() => void chat.create()} disabled={chat.busy}>
            New conversation
          </button>
        )}
      </div>
      <div
        className="nodrag nowheel grafy-agent__transcript"
        role="log"
        aria-label="Conversation transcript"
      >
        {chat.loading && <p>Loading conversation…</p>}
        {!chat.loading && !chat.events.length && (
          <p>Start a conversation with this Agent.</p>
        )}
        {chat.events.map((event) => (
          <div key={event.sequence}>
            {event.payload.kind === "turn_outcome" ? (
              <p>{event.payload.outcome}</p>
            ) : (
              <>
                <strong>
                  {event.payload.kind === "user_message" ? "You" : "Assistant"}
                </strong>
                <p style={{ whiteSpace: "pre-wrap" }}>{event.payload.text}</p>
                {canSend && (
                  <button
                    disabled={chat.busy || !!chat.active}
                    onClick={() => void chat.fork(event.sequence)}
                  >
                    Continue from here
                  </button>
                )}
              </>
            )}
          </div>
        ))}
        {chat.partial && (
          <p aria-label="Streaming reply" style={{ whiteSpace: "pre-wrap" }}>
            {chat.partial.text}
            {chat.partial.gap && " Reconnecting…"}
          </p>
        )}
      </div>
      {chat.error && <p role="alert">{chat.error}</p>}
      <form
        className="nodrag nowheel"
        onSubmit={(event) => {
          event.preventDefault();
          void chat.send(text).then((sent) => {
            if (sent) setText("");
          });
        }}
      >
        <textarea
          aria-label="Message"
          value={chat.retryText ?? text}
          onChange={(event) => setText(event.target.value)}
          disabled={
            !canSend ||
            chat.busy ||
            chat.loading ||
            !!chat.active ||
            !chat.conversationId ||
            chat.retryText !== undefined
          }
          placeholder={
            canSend ? "Message this Agent" : "You can read this conversation"
          }
        />
        {chat.active ? (
          <button
            type="button"
            disabled={!canSend || chat.busy}
            onClick={() => void chat.stop()}
          >
            Stop
          </button>
        ) : (
          <button
            disabled={
              !canSend || chat.busy || !chat.conversationId || !text.trim()
            }
          >
            {chat.retryText ? "Retry send" : "Send"}
          </button>
        )}
      </form>
    </>
  );
}
export default function AgentCard({ data, selected }: NodeProps<AgentNode>) {
  const { agent, scope, canEdit } = data;
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(agent);
  const [key, setKey] = React.useState("");
  const [configured, setConfigured] = React.useState(false);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    if (scope)
      void agentApi(scope)
        .model()
        .then((model) =>
          setConfigured(model.source === "agent" && model.key_configured),
        )
        .catch(() =>
          setError(
            "Model configuration is unavailable. Check the Agent settings.",
          ),
        );
  }, [scope]);
  async function changeKey(clear: boolean) {
    if (!scope) return;
    const value = key;
    setKey("");
    try {
      if (clear) await agentApi(scope).clearKey();
      else await agentApi(scope).key(value);
      setConfigured(!clear);
      setError("");
    } catch {
      setError("Unable to update the API key.");
    }
  }
  return (
    <section
      className="grafy-agent"
      aria-label={`Agent ${agent.name}`}
      style={{ width: "100%", height: "100%" }}
    >
      <NodeResizer
        isVisible={selected && canEdit}
        minWidth={300}
        minHeight={360}
        onResizeEnd={(_, size) =>
          data.configure({
            ...agent,
            width: size.width,
            height: size.height,
            position: { x: size.x, y: size.y },
          })
        }
      />
      <header>
        <strong>{agent.name}</strong>
        {canEdit && (
          <button
            className="nodrag"
            onClick={() => {
              setDraft(agent);
              setKey("");
              setEditing(!editing);
            }}
          >
            Configure
          </button>
        )}
      </header>
      {error && !editing && <p role="alert">{error}</p>}
      {editing ? (
        <form
          className="nodrag nowheel grafy-agent__configuration"
          onSubmit={(event) => {
            event.preventDefault();
            data.configure(draft);
            setEditing(false);
          }}
        >
          <label>
            Name
            <input
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </label>
          <label>
            Instructions
            <textarea
              value={draft.instructions}
              onChange={(event) =>
                setDraft({ ...draft, instructions: event.target.value })
              }
            />
          </label>
          <label>
            Model
            <select
              value={draft.model?.kind ?? "deployment"}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  model:
                    event.target.value === "custom"
                      ? { kind: "custom", endpoint: "", model: "" }
                      : { kind: "deployment" },
                })
              }
            >
              <option value="deployment">Deployment default</option>
              <option value="custom">Custom endpoint</option>
            </select>
          </label>
          {draft.model?.kind === "custom" && (
            <>
              <label>
                Endpoint
                <input
                  value={draft.model.endpoint}
                  onChange={(event) => {
                    if (draft.model?.kind === "custom")
                      setDraft({
                        ...draft,
                        model: { ...draft.model, endpoint: event.target.value },
                      });
                  }}
                />
              </label>
              <label>
                Model name
                <input
                  value={draft.model.model}
                  onChange={(event) => {
                    if (draft.model?.kind === "custom")
                      setDraft({
                        ...draft,
                        model: { ...draft.model, model: event.target.value },
                      });
                  }}
                />
              </label>
            </>
          )}
          <button type="submit">Save configuration</button>
          <button
            type="button"
            onClick={() => {
              setKey("");
              setEditing(false);
            }}
          >
            Cancel
          </button>
          <p>Custom model key {configured ? "configured" : "not configured"}</p>
          <input
            aria-label="API key"
            type="password"
            autoComplete="off"
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
          <button
            type="button"
            disabled={!scope || !key}
            onClick={() => void changeKey(false)}
          >
            Set key
          </button>
          <button
            type="button"
            disabled={!scope}
            onClick={() => void changeKey(true)}
          >
            Clear key
          </button>
          {error && <p role="alert">{error}</p>}
          <button type="button" onClick={data.remove}>
            Remove Agent
          </button>
        </form>
      ) : scope ? (
        <Conversation
          key={`${scope.graphId}/${agent.id}`}
          scope={scope}
          canSend={data.canSend}
        />
      ) : (
        <p>Save the Project to start a conversation.</p>
      )}
    </section>
  );
}
