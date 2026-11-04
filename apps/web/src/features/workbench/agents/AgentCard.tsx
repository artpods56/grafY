"use client";
import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  NodeResizeControl,
  NodeToolbar,
  Position,
  useReactFlow,
  useStoreApi,
  type NodeProps,
} from "@xyflow/react";
import {
  ArrowUp,
  ChevronDown,
  GitBranch,
  MessageSquare,
  Plus,
  RotateCcw,
  Settings2,
  Square,
  Trash2,
} from "lucide-react";
import type { SavedGraphAgent } from "@/lib/api/contract";
import type { components } from "@/lib/api/generated/grafy";
import { agentApi, type AgentScope } from "@/lib/api/agents";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  Menu,
  MenuContent,
  MenuRadioGroup,
  MenuRadioItem,
  MenuTrigger,
} from "@/components/ui/menu";
import { Notice } from "@/components/ui/notice";
import { RemoteSelectionRing } from "../room/RemoteSelectionRing";
import { SafeMarkdown } from "../canvas/safe-markdown";
import { NodeMenu } from "../canvas/nodes/NodeMenu";
import { ArtifactLabel } from "../canvas/nodes/ImageArtifactBody";
import { canvasCardRail } from "../canvas/nodes/CanvasCardLayout";
import { revealDelay, revealStyles } from "../canvas/nodes/PortBall";
import { resizeGrip } from "../canvas/nodes/LayoutResizeHandle";
import { Button, IconButton } from "@/components/ui/button";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { graphAgeLabel } from "@/features/workspaces/WorkspaceGraphPanel";
import type { AgentNode } from "./agent-node";
import { useAgentChat } from "./useAgentChat";

type AgentModel = components["schemas"]["AgentModelResponse"];

const PLATE_RADIUS = 12;
// The settings card beside an Agent, in screen pixels: it keeps its size at
// any zoom, like the other cards that float on the canvas.
const SETTINGS_WIDTH = 300;
const SETTINGS_GAP = 12;
// The right rail a card hangs its actions on: an 8px gap, then a 30px slot.
const RAIL_REACH = 38;

const OUTCOME_LABEL = {
  cancelled: "Stopped",
  failed: "Reply failed",
  interrupted: "Interrupted",
} as const;

const shimmer = stylex.keyframes({
  "0%": { backgroundPosition: "100% 0" },
  "100%": { backgroundPosition: "-100% 0" },
});

const s = stylex.create({
  // The Agent's whole box. Only its plate and what it has said take the
  // pointer (see the node's style in the Workbench); the rest of the box is
  // canvas, so a short conversation never leaves a dead patch above the plate.
  frame: {
    display: "flex",
    flexDirection: "column",
    justifyContent: "flex-end",
    width: "100%",
    height: "100%",
  },
  // The conversation is set on the canvas itself, above the plate, only as
  // tall as what has been said until it fills the box and scrolls; older
  // messages fade into the canvas as they scroll away.
  transcript: {
    flex: "0 1 auto",
    minHeight: 0,
    overflowY: "auto",
    overscrollBehavior: "contain",
    scrollbarWidth: "none",
    // The bottom fade only ever covers the thread's own bottom padding at
    // rest, so it shows only when what was said is scrolled up under the name.
    maskImage:
      "linear-gradient(to bottom, transparent 0, black 24px, black calc(100% - 16px), transparent 100%)",
    cursor: "auto",
    userSelect: "text",
    pointerEvents: "auto",
  },
  thread: {
    display: "flex",
    flexDirection: "column",
    gap: "14px",
    padding: { default: "24px 8px 16px", ":empty": 0 },
  },
  quiet: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
  quietCenter: { textAlign: "center" },
  continued: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  message: {
    position: "relative",
    display: "grid",
    justifyItems: "start",
    gap: "2px",
    minWidth: 0,
  },
  // The fork sits beside a person's bubble, so it costs no height.
  messageUser: {
    display: "flex",
    flexDirection: "row-reverse",
    alignItems: "center",
    gap: "4px",
  },
  userBubble: {
    maxWidth: "85%",
    boxSizing: "border-box",
    padding: "8px 12px",
    borderRadius: "10px",
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: `inset 0 0 0 1px ${tokens.colorDivider}`,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  reply: {
    justifySelf: "stretch",
    minWidth: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.55,
  },
  // "Continue from here" stays out of the reading until the message is
  // pointed at or focused; touch has no hover, so it stays visible there.
  forkReveal: {
    opacity: {
      default: 1,
      "@media (hover: hover) and (pointer: fine)": {
        default: 0,
        ":focus-visible": 1,
        [stylex.when.ancestor(":hover")]: 1,
        [stylex.when.ancestor(":focus-within")]: 1,
      },
    },
  },
  outcome: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 600,
    letterSpacing: "0.02em",
    textTransform: "uppercase",
    "::before": {
      content: "''",
      flex: 1,
      height: "1px",
      backgroundColor: tokens.colorDivider,
    },
    "::after": {
      content: "''",
      flex: 1,
      height: "1px",
      backgroundColor: tokens.colorDivider,
    },
  },
  outcomeFailed: { color: tokens.colorDanger },
  // "Thinking 3s", then "Writing 9s" once text arrives.
  status: {
    display: "flex",
    alignItems: "baseline",
    gap: "6px",
    fontSize: tokens.fontSizeSm,
  },
  statusWord: {
    color: {
      default: "transparent",
      "@media (prefers-reduced-motion: reduce)": tokens.colorSubtle,
    },
    backgroundImage: {
      default: `linear-gradient(90deg, ${tokens.colorSubtle} 0%, ${tokens.colorSubtle} 35%, ${tokens.colorTextEmphasis} 50%, ${tokens.colorSubtle} 65%, ${tokens.colorSubtle} 100%)`,
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    backgroundSize: "200% 100%",
    backgroundClip: "text",
    animationName: {
      default: shimmer,
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDuration: "1.8s",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
  statusTime: {
    color: tokens.colorSubtle,
    opacity: 0.65,
    fontVariantNumeric: "tabular-nums",
  },
  // The plate: a node's chrome fill and hairline, rounder because it holds a
  // second surface inside, and the same active-tier shadow while selected.
  plate: {
    position: "relative",
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    minHeight: 0,
    padding: "8px",
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: `${PLATE_RADIUS}px`,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    pointerEvents: "auto",
    transitionProperty: "box-shadow, border-color",
    transitionDuration: {
      default: "180ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  plateActive: {
    borderColor: tokens.colorBorderStrong,
    boxShadow: tokens.shadowNodeActive,
  },
  // Settings float beside the Agent, so the conversation stays as it is
  // while they are tweaked.
  settingsCard: {
    width: `${SETTINGS_WIDTH}px`,
    maxHeight: "min(600px, calc(100dvh - 32px))",
    boxSizing: "border-box",
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    padding: "4px 8px 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: `${PLATE_RADIUS}px`,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "auto",
  },
  settingsTitle: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
  },
  // As on a raster card: the name row sits above the plate, and the plate's
  // actions hang on the rail to its right while it is picked up.
  head: {
    flexShrink: 0,
    minWidth: 0,
    paddingInline: "2px",
    cursor: "grab",
    pointerEvents: "auto",
  },
  body: {
    position: "relative",
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
  },
  railActions: { gap: "2px" },
  // The "⋯" trigger's shape, so the rail's two buttons read as one stack.
  settingsHeader: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    height: "34px",
    flexShrink: 0,
    paddingInline: "2px",
  },
  settingsMark: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  // What the person writes into sits on a second, raised surface.
  inputBox: {
    display: "grid",
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: {
      default: "none",
      ":focus-within": `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
    },
  },
  composerInput: {
    minWidth: 0,
    height: "68px",
    boxSizing: "border-box",
    padding: "10px 12px",
    borderWidth: 0,
    outline: "none",
    backgroundColor: "transparent",
    color: tokens.colorText,
    cursor: { default: "text", ":disabled": "default" },
    fontFamily: "inherit",
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.45,
    resize: "none",
    "::placeholder": { color: tokens.colorSubtle },
  },
  footer: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    minWidth: 0,
  },
  // The conversation picker gives way before the send button does.
  chipShrink: { flexShrink: 1, minWidth: 0 },
  chipIcon: { flexShrink: 0, color: tokens.colorSubtle },
  sendSlot: { marginLeft: "auto" },
  chipLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  popup: {
    maxHeight: "min(320px, var(--available-height))",
  },
  settings: {
    minHeight: 0,
    display: "grid",
    alignContent: "start",
    gap: "14px",
    padding: "6px 4px 4px",
    overflowY: "auto",
    overscrollBehavior: "contain",
    cursor: "auto",
  },
  settingsForm: {
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  },
  field: {
    display: "grid",
    gap: "5px",
    minWidth: 0,
    margin: 0,
    padding: 0,
    borderWidth: 0,
    borderStyle: "none",
  },
  label: {
    padding: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  // A legend is not a grid item, so the fieldset gap does not reach it.
  legend: { marginBottom: "5px" },
  hint: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.4,
  },
  keyStatusOn: { color: tokens.colorSuccess },
  keyRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "5px",
  },
  linkButton: {
    flexShrink: 0,
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: {
      default: tokens.colorSubtle,
      ":hover": tokens.colorDanger,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "default" },
    fontSize: "10px",
    fontWeight: 500,
  },
  actions: {
    flexShrink: 0,
    display: "flex",
    justifyContent: "flex-end",
    gap: "6px",
  },
  // The canvas corner grip, a pixel further in for the rounder plate, on
  // React Flow's resize control so zoom, snapping to its min size and the end
  // event stay its job.
  gripInset: { right: "4px", bottom: "4px" },
});

/** React Flow's own handle CSS is two classes deep; only inline style outranks it. */
const RESIZE_CONTROL_STYLE: React.CSSProperties = {
  width: 16,
  height: 16,
  translate: "-100% -100%",
  border: 0,
  borderRadius: 3,
  background: "transparent",
  cursor: "nwse-resize",
  pointerEvents: "auto",
};

function interactive(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nopan nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

function Conversation({
  scope,
  agentName,
  canSend,
  head,
  rail,
  notice,
  plate,
}: {
  scope: AgentScope;
  agentName: string;
  canSend: boolean;
  head: React.ReactNode;
  rail: React.ReactNode;
  notice: React.ReactNode;
  plate: ReturnType<typeof stylex.props>;
}) {
  const chat = useAgentChat(scope);
  const [text, setText] = React.useState("");
  const [now, setNow] = React.useState(() => Date.now());
  const transcriptRef = React.useRef<HTMLDivElement>(null);
  const formRef = React.useRef<HTMLFormElement>(null);
  // Every conversation starts as "New conversation", so until conversations
  // are named each is numbered in the order it was started, which a newer
  // conversation never shifts. The menu lists the newest first.
  const byAge = [...chat.conversations].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  const titles = new Map(
    byAge.map((item, index) => [
      item.id,
      item.title && item.title !== "New conversation"
        ? item.title
        : `Conversation ${index + 1}`,
    ]),
  );
  const sourceId = chat.conversations.find(
    (item) => item.id === chat.conversationId,
  )?.source_conversation_id;
  const composerLocked =
    !canSend ||
    chat.busy ||
    chat.loading ||
    !!chat.active ||
    !chat.conversationId ||
    chat.retryText !== undefined;
  const replying =
    !!chat.active &&
    !chat.events.some(
      (event) =>
        event.turn_id === chat.active?.turn.id &&
        event.payload.kind === "assistant_message",
    );
  const streaming = !!chat.partial && !!(chat.partial.text || chat.partial.gap);
  const startedAt = replying ? chat.active?.turn.created_at : undefined;
  const elapsed = startedAt
    ? Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000))
    : 0;

  React.useEffect(() => {
    if (!startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  React.useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [chat.events.length, chat.partial?.text, replying]);

  return (
    <>
      <div
        ref={transcriptRef}
        role="log"
        aria-label="Conversation transcript"
        {...interactive(stylex.props(s.transcript))}
      >
        <div {...stylex.props(s.thread)}>
          {sourceId ? (
            <span {...stylex.props(s.continued)}>
              <GitBranch size={11} />
              Continued from {titles.get(sourceId) ?? "another conversation"}
            </span>
          ) : null}
          {chat.loading ? (
            <p {...stylex.props(s.quiet, s.quietCenter)}>
              Loading conversation…
            </p>
          ) : canSend ? null : !chat.conversationId ? (
            <p {...stylex.props(s.quiet, s.quietCenter)}>
              No conversations with this Agent yet.
            </p>
          ) : !chat.events.length && !chat.partial ? (
            <p {...stylex.props(s.quiet, s.quietCenter)}>
              Nothing has been said yet.
            </p>
          ) : null}
          {chat.events.map((event) => {
            if (event.payload.kind === "turn_outcome") {
              const outcome = event.payload.outcome;
              if (outcome === "completed") return null;
              return (
                <div
                  key={event.sequence}
                  role="note"
                  title={event.payload.detail ?? undefined}
                  {...stylex.props(
                    s.outcome,
                    outcome === "failed" ? s.outcomeFailed : null,
                  )}
                >
                  {OUTCOME_LABEL[outcome]}
                </div>
              );
            }
            if (
              event.payload.kind === "tool_call" ||
              event.payload.kind === "tool_result" ||
              event.payload.kind === "confirmation_requested"
            ) {
              // Tool events are drawn by the tool rows, not as chat bubbles.
              return null;
            }
            const fromUser = event.payload.kind === "user_message";
            return (
              <div
                key={event.sequence}
                {...stylex.props(
                  s.message,
                  fromUser ? s.messageUser : null,
                  stylex.defaultMarker(),
                )}
              >
                {fromUser ? (
                  <div {...stylex.props(s.userBubble)}>
                    {event.payload.text}
                  </div>
                ) : (
                  <div {...stylex.props(s.reply)}>
                    <SafeMarkdown>{event.payload.text}</SafeMarkdown>
                  </div>
                )}
                {canSend && (
                  <IconButton
                    label="Continue from here"
                    title="Continue from here in a new conversation"
                    size="xs"
                    disabled={chat.busy || !!chat.active}
                    onClick={() => void chat.fork(event.sequence)}
                    xstyle={s.forkReveal}
                  >
                    <GitBranch size={12} />
                  </IconButton>
                )}
              </div>
            );
          })}
          {replying || streaming ? (
            <div {...stylex.props(s.message)}>
              {replying ? (
                <div {...stylex.props(s.status)}>
                  <span role="status" {...stylex.props(s.statusWord)}>
                    {streaming ? "Writing" : "Thinking"}
                  </span>
                  <span aria-hidden="true" {...stylex.props(s.statusTime)}>
                    {elapsed < 60
                      ? `${elapsed}s`
                      : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
                  </span>
                </div>
              ) : null}
              {streaming ? (
                <div aria-label="Streaming reply" {...stylex.props(s.reply)}>
                  <SafeMarkdown>{chat.partial?.text ?? ""}</SafeMarkdown>
                </div>
              ) : null}
              {chat.partial?.gap ? (
                <p role="status" {...stylex.props(s.quiet)}>
                  Reconnecting…
                </p>
              ) : null}
            </div>
          ) : null}
          {chat.error && <Notice tone="danger">{chat.error}</Notice>}
        </div>
      </div>
      {head}
      <div {...stylex.props(s.body)}>
        {rail}
        <form
          ref={formRef}
          {...plate}
          onSubmit={(event) => {
            event.preventDefault();
            if (chat.active || !canSend || chat.busy) return;
            if (chat.retryText === undefined && !text.trim()) return;
            void chat.send(text).then((sent) => {
              if (sent) setText("");
            });
          }}
        >
          {notice}
          <div {...interactive(stylex.props(s.inputBox))}>
            <textarea
              aria-label="Message"
              value={chat.retryText ?? text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  formRef.current?.requestSubmit();
                }
              }}
              disabled={composerLocked}
              placeholder={
                !canSend
                  ? "You can read this conversation"
                  : !chat.conversationId
                    ? `Start a conversation to message ${agentName}`
                    : chat.events.length
                      ? "Add a follow-up…"
                      : `Ask ${agentName} something`
              }
              {...stylex.props(s.composerInput)}
            />
          </div>
          <div {...interactive(stylex.props(s.footer))}>
            {chat.conversations.length ? (
              <Menu>
                <MenuTrigger
                  aria-label="Conversation"
                  disabled={chat.busy}
                  render={
                    <Button variant="soft" size="sm" xstyle={s.chipShrink} />
                  }
                >
                  <MessageSquare size={13} {...stylex.props(s.chipIcon)} />
                  <span {...stylex.props(s.chipLabel)}>
                    {titles.get(chat.conversationId) ?? "Choose a conversation"}
                  </span>
                  <ChevronDown size={12} {...stylex.props(s.chipIcon)} />
                </MenuTrigger>
                <MenuContent
                  side="top"
                  align="start"
                  sideOffset={6}
                  xstyle={s.popup}
                >
                  <MenuRadioGroup
                    value={chat.conversationId ?? ""}
                    onValueChange={(value) => chat.select(value)}
                  >
                    {byAge.toReversed().map((item) => (
                      <MenuRadioItem
                        key={item.id}
                        value={item.id}
                        detail={
                          <>
                            {graphAgeLabel(item.updated_at)}
                            {item.source_conversation_id ? " · continued" : ""}
                          </>
                        }
                      >
                        {titles.get(item.id)}
                      </MenuRadioItem>
                    ))}
                  </MenuRadioGroup>
                </MenuContent>
              </Menu>
            ) : null}
            {!canSend ? null : chat.conversations.length ? (
              <IconButton
                label="New conversation"
                variant="soft"
                size="md"
                onClick={() => void chat.create()}
                disabled={chat.busy}
              >
                <Plus size={14} />
              </IconButton>
            ) : (
              <Button
                variant="soft"
                size="sm"
                title="New conversation"
                onClick={() => void chat.create()}
                disabled={chat.busy}
              >
                <Plus size={14} {...stylex.props(s.chipIcon)} />
                New conversation
              </Button>
            )}
            {chat.active ? (
              <IconButton
                label="Stop"
                variant="primary"
                size="lg"
                disabled={!canSend || chat.busy}
                onClick={() => void chat.stop()}
                xstyle={s.sendSlot}
              >
                <Square size={10} fill="currentColor" />
              </IconButton>
            ) : chat.retryText !== undefined ? (
              <IconButton
                type="submit"
                label="Retry send"
                variant="primary"
                size="lg"
                disabled={!canSend || chat.busy}
                xstyle={s.sendSlot}
              >
                <RotateCcw size={13} />
              </IconButton>
            ) : (
              <IconButton
                type="submit"
                label="Send"
                title="Send · Shift + Enter for a new line"
                variant="primary"
                size="lg"
                disabled={
                  !canSend || chat.busy || !chat.conversationId || !text.trim()
                }
                xstyle={s.sendSlot}
              >
                <ArrowUp size={15} />
              </IconButton>
            )}
          </div>
        </form>
      </div>
    </>
  );
}

function AgentSettings({
  agent,
  scope,
  keyConfigured,
  onKeyConfigured,
  onSave,
  onCancel,
}: {
  agent: SavedGraphAgent;
  scope: AgentScope | null;
  keyConfigured: boolean;
  onKeyConfigured: (configured: boolean) => void;
  onSave: (agent: SavedGraphAgent) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = React.useState(agent);
  const [key, setKey] = React.useState("");
  const [error, setError] = React.useState("");
  const custom = draft.model?.kind === "custom" ? draft.model : null;

  async function changeKey(clear: boolean) {
    if (!scope) return;
    const value = key;
    setKey("");
    try {
      if (clear) await agentApi(scope).clearKey();
      else await agentApi(scope).key(value);
      onKeyConfigured(!clear);
      setError("");
    } catch {
      setError("Unable to update the API key.");
    }
  }

  return (
    <form
      aria-label="Agent settings"
      {...interactive(stylex.props(s.settingsForm))}
      onSubmit={(event) => {
        event.preventDefault();
        onSave(draft);
      }}
    >
      <div {...stylex.props(s.settings)}>
        <Field label="Name">
          <TextInput
            value={draft.name}
            onChange={(event) =>
              setDraft({ ...draft, name: event.target.value })
            }
          />
        </Field>
        <Field label="Instructions">
          <TextArea
            value={draft.instructions}
            placeholder="How this Agent should answer"
            onChange={(event) =>
              setDraft({ ...draft, instructions: event.target.value })
            }
          />
        </Field>
        <fieldset {...stylex.props(s.field)}>
          <legend {...stylex.props(s.label, s.legend)}>Model</legend>
          <SegmentedControl
            aria-label="Model"
            value={draft.model?.kind ?? "deployment"}
            options={[
              { value: "deployment", label: "Deployment default" },
              { value: "custom", label: "Custom endpoint" },
            ]}
            onValueChange={(kind) =>
              setDraft({
                ...draft,
                model:
                  kind === "custom"
                    ? { kind: "custom", endpoint: "", model: "" }
                    : { kind: "deployment" },
              })
            }
          />
          {!custom ? (
            <p {...stylex.props(s.hint)}>
              Uses the model this deployment&apos;s operator configured.
            </p>
          ) : null}
        </fieldset>
        {custom ? (
          <>
            <Field label="Endpoint">
              <TextInput
                mono
                value={custom.endpoint}
                placeholder="https://models.example/v1"
                spellCheck={false}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    model: { ...custom, endpoint: event.target.value },
                  })
                }
              />
            </Field>
            <Field label="Model name">
              <TextInput
                mono
                value={custom.model}
                placeholder="gpt-5-mini"
                spellCheck={false}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    model: { ...custom, model: event.target.value },
                  })
                }
              />
            </Field>
          </>
        ) : null}
        {custom || keyConfigured ? (
          <Field
            label="API key"
            aside={
              <>
                <span
                  role="status"
                  {...stylex.props(keyConfigured ? s.keyStatusOn : null)}
                >
                  {keyConfigured ? "Configured" : "Not set"}
                </span>
                {keyConfigured ? (
                  <>
                    {" · "}
                    <button
                      type="button"
                      disabled={!scope}
                      onClick={() => void changeKey(true)}
                      {...stylex.props(s.linkButton)}
                    >
                      Clear key
                    </button>
                  </>
                ) : null}
              </>
            }
            description={
              scope
                ? "Write-only · the stored key cannot be read back."
                : "Save the Project before setting a key."
            }
          >
            <div {...stylex.props(s.keyRow)}>
              <TextInput
                mono
                type="password"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                data-1p-ignore
                data-lpignore="true"
                data-bwignore
                value={key}
                placeholder={keyConfigured ? "Replace key" : "Enter key"}
                disabled={!scope}
                onChange={(event) => setKey(event.target.value)}
              />
              <Button
                variant="soft"
                disabled={!scope || !key}
                onClick={() => void changeKey(false)}
              >
                Set key
              </Button>
            </div>
          </Field>
        ) : null}
        {error && <Notice tone="danger">{error}</Notice>}
      </div>
      <div {...stylex.props(s.actions)}>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!draft.name.trim()}>
          Save
        </Button>
      </div>
    </form>
  );
}

export default function AgentCard({
  id,
  data,
  selected,
}: NodeProps<AgentNode>) {
  const { agent, scope, canEdit } = data;
  // Where the settings are open: beside the Agent on a side with room for
  // them, chosen once on opening so a pan never drops a draft. With no room
  // on either side the canvas slides over to make some, and only a screen
  // too narrow for the Agent and its settings together gets a dialog.
  const [editing, setEditing] = React.useState<
    "left" | "right" | "dialog" | null
  >(null);
  const store = useStoreApi();
  const flow = useReactFlow();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [model, setModel] = React.useState<AgentModel | null>(null);
  const [keyConfigured, setKeyConfigured] = React.useState(false);
  const [error, setError] = React.useState("");
  const modelChoice = JSON.stringify(agent.model ?? null);
  React.useEffect(() => {
    if (!scope) return;
    let alive = true;
    void agentApi(scope)
      .model()
      .then((next) => {
        if (!alive) return;
        setModel(next);
        setKeyConfigured(next.source === "agent" && next.key_configured);
        setError("");
      })
      .catch(() => {
        if (alive)
          setError(
            "Model configuration is unavailable. Check the Agent settings.",
          );
      });
    return () => {
      alive = false;
    };
  }, [scope, modelChoice]);

  const openSettings = () => {
    const { nodeLookup, transform, width } = store.getState();
    const node = nodeLookup.get(id);
    const [x, y, zoom] = transform;
    const left = (node?.internals.positionAbsolute.x ?? 0) * zoom + x;
    const right = left + (node?.measured.width ?? 0) * zoom;
    const room = RAIL_REACH + SETTINGS_GAP + SETTINGS_WIDTH;
    const margin = 16;
    if (right + room <= width) setEditing("right");
    else if (left - SETTINGS_GAP - SETTINGS_WIDTH >= 0) setEditing("left");
    else if (right - left + room + 2 * margin <= width) {
      const still = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      void flow.setViewport(
        { x: x - (right + room + margin - width), y, zoom },
        { duration: still ? 0 : 220 },
      );
      setEditing("right");
    } else setEditing("dialog");
  };
  const plate = stylex.props(s.plate, selected ? s.plateActive : null);
  const ring =
    !selected && data.remoteSelectionColor ? (
      <RemoteSelectionRing
        color={data.remoteSelectionColor}
        radius={PLATE_RADIUS}
      />
    ) : null;
  // The raster card's chrome: the name and what answers for it above the
  // plate, and the plate's actions on the rail to its right, out while the
  // Agent is picked up (or its menu or settings are open).
  const head = (
    <header {...stylex.props(s.head)}>
      <ArtifactLabel
        title={agent.name}
        contract={model?.model_name ?? "Agent"}
        contractTooltip={
          model
            ? `${model.model_name} · ${model.source === "agent" ? "this Agent's endpoint" : "deployment default"}`
            : undefined
        }
        selected={Boolean(selected)}
      />
    </header>
  );
  const showActions = Boolean(selected) || menuOpen || Boolean(editing);
  const actions = stylex.props(
    canvasCardRail.actions,
    s.railActions,
    revealStyles(showActions, "output"),
  );
  const rail = (
    <div {...stylex.props(canvasCardRail.rail, canvasCardRail.right)}>
      <div
        data-agent-chrome={showActions ? "on" : "off"}
        {...actions}
        className={`nodrag nopan ${actions.className ?? ""}`}
        style={revealDelay(0)}
      >
        <NodeMenu
          label={`Actions for ${agent.name}`}
          info={{
            title: agent.name,
            lines: [
              agent.instructions.trim() ||
                "Answers in conversations here on the canvas.",
            ],
            footer: model?.model_name,
          }}
          items={
            canEdit
              ? [
                  {
                    id: "configure",
                    label: "Configure",
                    icon: <Settings2 size={13} />,
                    onClick: () => {
                      if (!editing) openSettings();
                    },
                  },
                  {
                    id: "remove",
                    label: "Remove Agent",
                    icon: <Trash2 size={13} />,
                    danger: true,
                    onClick: data.remove,
                  },
                ]
              : []
          }
          onOpenChange={setMenuOpen}
        />
        {canEdit ? (
          <IconButton
            label="Configure"
            size="xs"
            shape="round"
            pressed={!!editing}
            onClick={() => (editing ? setEditing(null) : openSettings())}
          >
            <Settings2 size={13} />
          </IconButton>
        ) : null}
      </div>
    </div>
  );
  const notice = (
    <>
      {ring}
      {error && <Notice tone="danger">{error}</Notice>}
    </>
  );

  const settings = (
    <AgentSettings
      agent={agent}
      scope={scope}
      keyConfigured={keyConfigured}
      onKeyConfigured={setKeyConfigured}
      onSave={(next) => {
        data.configure(next);
        setEditing(null);
      }}
      onCancel={() => setEditing(null)}
    />
  );

  return (
    <section aria-label={`Agent ${agent.name}`} {...stylex.props(s.frame)}>
      {scope ? (
        <Conversation
          key={`${scope.graphId}/${agent.id}`}
          scope={scope}
          agentName={agent.name}
          canSend={data.canSend}
          head={head}
          rail={rail}
          notice={notice}
          plate={plate}
        />
      ) : (
        <>
          {head}
          <div {...stylex.props(s.body)}>
            {rail}
            <div {...plate}>
              {notice}
              <div {...interactive(stylex.props(s.inputBox))}>
                <textarea
                  aria-label="Message"
                  disabled
                  placeholder="Save the Project to start a conversation."
                  {...stylex.props(s.composerInput)}
                />
              </div>
              <div {...stylex.props(s.footer)}>
                <IconButton
                  label="Send"
                  variant="primary"
                  size="lg"
                  disabled
                  xstyle={s.sendSlot}
                >
                  <ArrowUp size={15} />
                </IconButton>
              </div>
            </div>
          </div>
        </>
      )}
      {editing === "dialog" ? (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
        >
          <DialogContent size="compact">
            <DialogHeader>
              <DialogTitle>{agent.name} settings</DialogTitle>
            </DialogHeader>
            <DialogBody>{settings}</DialogBody>
          </DialogContent>
        </Dialog>
      ) : editing ? (
        <NodeToolbar
          isVisible
          position={editing === "right" ? Position.Right : Position.Left}
          align="end"
          // Past the rail on the right, so the card never covers its actions.
          offset={
            editing === "right" ? RAIL_REACH + SETTINGS_GAP : SETTINGS_GAP
          }
          className="nodrag nopan nowheel"
          // Above a neighbour that selection lifted, which React Flow's own
          // toolbar z-index (this node's, plus one) would sit under.
          style={{ zIndex: 1001 }}
        >
          <div
            {...stylex.props(s.settingsCard)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setEditing(null);
            }}
          >
            <div {...stylex.props(s.settingsHeader)}>
              <span aria-hidden="true" {...stylex.props(s.settingsMark)}>
                <Settings2 size={13} />
              </span>
              <span {...stylex.props(s.settingsTitle)}>Settings</span>
            </div>
            {settings}
          </div>
        </NodeToolbar>
      ) : null}
      {selected && canEdit ? (
        <NodeResizeControl
          position="bottom-right"
          minWidth={300}
          minHeight={360}
          style={RESIZE_CONTROL_STYLE}
          className="nodrag nopan"
          onResizeEnd={(_, size) =>
            data.configure({
              ...agent,
              width: size.width,
              height: size.height,
              position: { x: size.x, y: size.y },
            })
          }
        >
          <span
            aria-hidden="true"
            {...stylex.props(resizeGrip.glyph, s.gripInset)}
          />
        </NodeResizeControl>
      ) : null}
    </section>
  );
}
