"use client";

/**
 * The floating chrome of the on-scan TIFF text-regions editor.
 *
 * A map scan carries 1,500+ regions, so there is no list of them here and there
 * never will be: a person works on the scan itself, and these two overlays carry
 * only what belongs to the region under the pointer. The rail on the right is the
 * tool box — the shape tools, the eraser, and the bulk actions a selection earns.
 * The bar along the top is the reading of the one region in hand, or the merge and
 * delete that a handful of shift-picked regions are given together, plus the
 * messages that must not be missed: a failed save, an about-to-be-thrown-away
 * edit, and the eraser mode, which leaves no cursor of its own to remind anyone.
 *
 * Nothing here decides anything about regions. It renders a reducer state, turns
 * clicks and keystrokes into actions, and keeps every gesture inside itself so the
 * card drag or the OpenSeadragon pan underneath never starts.
 */

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Check,
  Combine,
  Eraser,
  MousePointer2,
  Pentagon,
  Redo2,
  Square,
  Trash2,
  Undo2,
  X,
} from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type {
  TiffTextRegionsEditorAction,
  TiffTextRegionsEditorState,
} from "./tiff-text-regions-editor-reducer";
import {
  MIN_POLYGON_VERTICES,
  regionText,
  type EditableTextRegion,
} from "./types";

export interface TiffRegionsEditControlsProps {
  state: TiffTextRegionsEditorState;
  dispatch: React.Dispatch<TiffTextRegionsEditorAction>;
  /** True when rendered inside the fullscreen WorkbenchModal, false on the inline canvas card. */
  inModal: boolean;
  /** False when this card is currently behind an open fullscreen modal, so document shortcuts only fire once. */
  shortcutsActive: boolean;
  saving: boolean;
  error: string | null;
  onSave: () => void;
  onClose: () => void;
}

/**
 * The rail's icon step. A modal has the room for `xs` (22px); a card floats over a
 * scan whose own details are worth more than the toolbox, so it takes `2xs` (20px),
 * the kit's furniture step.
 */
const RAIL_ICON_SIZE = { modal: 15, card: 13 } as const;
const RAIL_CONTROL_SIZE = { modal: "xs", card: "2xs" } as const;

const s = stylex.create({
  rail: {
    position: "absolute",
    right: 6,
    top: "50%",
    transform: "translateY(-50%)",
    zIndex: 3,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 2,
    padding: 4,
    backgroundColor: tokens.colorSurface,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    // `shadowNode` is the floating-card elevation: these overlays sit at the same
    // height as the scan they float over, and there is no `shadowMd` to borrow.
    boxShadow: tokens.shadowNode,
  },
  divider: {
    height: 1,
    width: "100%",
    backgroundColor: tokens.colorBorder,
    margin: "2px 0",
    flexShrink: 0,
  },
  /**
   * The strip's wrapper takes no pointer events at all: it spans the scan from edge
   * to edge, and the empty space beside a pill still has to pan the page.
   */
  bar: {
    position: "absolute",
    top: 6,
    left: 6,
    right: 44,
    zIndex: 3,
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 4,
    pointerEvents: "none",
  },
  pill: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space1,
    minWidth: 0,
    maxWidth: "100%",
    padding: "3px 5px",
    boxSizing: "border-box",
    // The wrapper takes no pointer events; a pill does, and it is the only thing
    // a person can actually hit here.
    pointerEvents: "auto",
    backgroundColor: tokens.colorSurface,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  /**
   * A message inside the pill. Its own wash is translucent, which is fine in a form
   * and useless over a scan, so the pill keeps the ground and the Notice keeps only
   * its colour, its role, and its action slot.
   */
  notice: {
    flex: 1,
    minWidth: 0,
    padding: 0,
    backgroundColor: "transparent",
    borderRadius: 0,
    fontSize: "inherit",
    lineHeight: 1.3,
  },
  /** Which region the reading belongs to, counted the way a person counts them. */
  badge: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
    fontWeight: 600,
  },
  /** The recognizer's own score for the words it read. */
  score: {
    flexShrink: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
  },
  reading: {
    // The input takes whatever the pill has left after the badges, and gives ground
    // to none of them: a long transcription scrolls, the `#12` never disappears.
    flex: "1 1 auto",
    minWidth: 80,
    maxWidth: 320,
  },
  /** How many regions the bulk pill is about. The count changes under the cursor. */
  count: {
    flexShrink: 0,
    fontVariantNumeric: "tabular-nums",
    fontWeight: 600,
  },
  /**
   * A mode the pointer cannot see. Eraser changes what a click means and nothing
   * else, so the word for it has to sit somewhere on screen while it is armed. It
   * takes the wrapping the pill allows: on a narrow card the sentence breaks, and
   * the rail beside it keeps its ground.
   */
  hint: {
    minWidth: 0,
    color: tokens.colorSubtle,
  },
});

/** The region a keystroke or the reading bar is about, or nothing when the index is stale. */
function selectedRegion(
  state: TiffTextRegionsEditorState,
): { readonly index: number; readonly region: EditableTextRegion } | null {
  const selection = state.selection;
  if (selection === null) return null;
  const region = state.payload.regions[selection.region];
  if (!region) return null;
  return { index: selection.region, region };
}

/**
 * How sure the recognizer was, as a person reads it.
 *
 * The contract keeps `confidence` in 0…1 and the detector's `score` alongside it,
 * so a value already past 1 is a producer that wrote a percentage and gets one
 * rather than being multiplied into four digits.
 */
function confidenceBadge(value: number): string {
  const percent = value <= 1 ? value * 100 : value;
  return `${Math.round(percent)}%`;
}

/** The score this region carries, from whichever of the two wire keys holds it. */
function regionConfidence(region: EditableTextRegion): number | null {
  if (region.reading?.confidence != null) return region.reading.confidence;
  const score = region.extra["score"];
  return typeof score === "number" && Number.isFinite(score) ? score : null;
}

/** A keystroke typed *into* something: its key belongs to that control, not to us. */
function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

export function TiffRegionsEditControls({
  state,
  dispatch,
  inModal,
  shortcutsActive,
  saving,
  error,
  onSave,
  onClose,
}: TiffRegionsEditControlsProps): React.ReactElement {
  const [discardAsked, setDiscardAsked] = React.useState(false);
  const readingRef = React.useRef<HTMLInputElement>(null);

  // Two or more regions in hand is its own subject: they are acted on in bulk, so
  // the one region's transcription has nothing to say and is not drawn.
  const multi = state.selectedRegions.length >= 2;
  const selected = multi ? null : selectedRegion(state);
  const eraserHint =
    state.mode === "eraser" && state.selectedRegions.length === 0;
  const reading = selected === null ? "" : regionText(selected.region);
  const confidence =
    selected === null ? null : regionConfidence(selected.region);
  const iconSize = inModal ? RAIL_ICON_SIZE.modal : RAIL_ICON_SIZE.card;
  const controlSize = inModal
    ? RAIL_CONTROL_SIZE.modal
    : RAIL_CONTROL_SIZE.card;
  const rail = stylex.props(s.rail);

  const closeDiscardPrompt = React.useCallback(
    () => setDiscardAsked(false),
    [],
  );

  const requestClose = React.useCallback(() => {
    // An edit that was never written is a person's work: it goes when they say so,
    // not when the control that happens to say "close" is clicked.
    if (state.isDirty) setDiscardAsked(true);
    else onClose();
  }, [onClose, state.isDirty]);

  // Derived, so the prompt retires the moment there is nothing to discard — an
  // undo back to the saved bytes, or a save that finally landed — without a second
  // copy of "is there work outstanding?" kept in a `useEffect`.
  const confirmDiscard = discardAsked && state.isDirty;

  useRegionEditShortcuts({
    active: shortcutsActive && !saving,
    state,
    dispatch,
    confirmDiscard,
    onCloseDiscard: closeDiscardPrompt,
  });

  return (
    <>
      <div
        role="toolbar"
        aria-label="Text region tools"
        aria-orientation="vertical"
        className={`nodrag nopan ${rail.className ?? ""}`}
        style={rail.style}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <IconButton
          label="Select region (Shift+click for multiple)"
          size={controlSize}
          pressed={state.mode === "select"}
          disabled={saving}
          onClick={() => dispatch({ type: "set_mode", mode: "select" })}
        >
          <MousePointer2 size={iconSize} />
        </IconButton>
        <IconButton
          label="Draw box"
          size={controlSize}
          pressed={state.mode === "draw_box"}
          disabled={saving}
          onClick={() => dispatch({ type: "set_mode", mode: "draw_box" })}
        >
          <Square size={iconSize} />
        </IconButton>
        <IconButton
          label="Draw polygon"
          size={controlSize}
          pressed={state.mode === "draw_polygon"}
          disabled={saving}
          onClick={() => dispatch({ type: "set_mode", mode: "draw_polygon" })}
        >
          <Pentagon size={iconSize} />
        </IconButton>
        <IconButton
          label="Erase regions (E)"
          size={controlSize}
          pressed={state.mode === "eraser"}
          disabled={saving}
          onClick={() => dispatch({ type: "set_mode", mode: "eraser" })}
        >
          <Eraser size={iconSize} />
        </IconButton>

        <div {...stylex.props(s.divider)} />

        <IconButton
          label="Merge selected regions (M)"
          size={controlSize}
          disabled={state.selectedRegions.length < 2 || saving}
          onClick={() => dispatch({ type: "merge_selected_regions" })}
        >
          <Combine size={iconSize} />
        </IconButton>
        <IconButton
          label="Undo"
          size={controlSize}
          disabled={state.past.length === 0 || saving}
          onClick={() => dispatch({ type: "undo" })}
        >
          <Undo2 size={iconSize} />
        </IconButton>
        <IconButton
          label="Redo"
          size={controlSize}
          disabled={state.future.length === 0 || saving}
          onClick={() => dispatch({ type: "redo" })}
        >
          <Redo2 size={iconSize} />
        </IconButton>
        <IconButton
          label={
            state.selectedRegions.length > 1
              ? `Delete ${state.selectedRegions.length} selected regions`
              : "Delete selected region"
          }
          size={controlSize}
          disabled={state.selectedRegions.length === 0 || saving}
          onClick={() => dispatch({ type: "delete_selected_region" })}
        >
          <Trash2 size={iconSize} />
        </IconButton>

        <div {...stylex.props(s.divider)} />

        <IconButton
          label={saving ? "Saving…" : "Save new version"}
          size={controlSize}
          variant={state.isDirty ? "accent" : undefined}
          disabled={!state.isDirty || saving}
          onClick={onSave}
        >
          <Check size={iconSize} />
        </IconButton>
        <IconButton
          label="Close editor"
          size={controlSize}
          disabled={saving}
          onClick={requestClose}
        >
          <X size={iconSize} />
        </IconButton>
      </div>

      {error !== null ||
      confirmDiscard ||
      multi ||
      eraserHint ||
      selected !== null ? (
        <div
          className="nodrag nopan"
          {...stylex.props(s.bar)}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {error !== null ? (
            <div {...stylex.props(s.pill)}>
              <Notice tone="danger" xstyle={s.notice}>
                {error}
              </Notice>
            </div>
          ) : null}
          {confirmDiscard ? (
            <div {...stylex.props(s.pill)}>
              <Notice
                tone="warning"
                xstyle={s.notice}
                action={
                  <>
                    <Button
                      size="xs"
                      variant="secondary"
                      onClick={closeDiscardPrompt}
                    >
                      Keep editing
                    </Button>
                    <Button size="xs" variant="danger" onClick={onClose}>
                      Discard
                    </Button>
                  </>
                }
              >
                Unsaved edits — discard?
              </Notice>
            </div>
          ) : null}
          {multi ? (
            // The bulk pill. There is no transcription to read across three regions,
            // and there is something to do to all of them at once, so the pill says
            // how many are in hand and offers the two verbs that mean "these".
            <div className="nodrag nopan" {...stylex.props(s.pill)}>
              <span
                {...stylex.props(s.count)}
              >{`${state.selectedRegions.length} regions selected`}</span>
              <Button
                size="xs"
                variant="primary"
                disabled={saving}
                onClick={() => dispatch({ type: "merge_selected_regions" })}
              >
                Merge
              </Button>
              <Button
                size="xs"
                variant="danger"
                disabled={saving}
                onClick={() => dispatch({ type: "delete_selected_region" })}
              >
                Delete
              </Button>
              <IconButton
                label="Clear selection"
                size="2xs"
                disabled={saving}
                onClick={() => dispatch({ type: "clear_selection" })}
              >
                <X size={11} />
              </IconButton>
            </div>
          ) : null}
          {selected !== null ? (
            <div
              className="nodrag nopan"
              {...stylex.props(s.pill)}
              onKeyDown={(event) => {
                // Typing belongs to the transcription, and a `Delete` in the middle
                // of a word must not reach the shortcuts that eat a region. Escape is
                // the one key a person means as "leave this field".
                if (event.key === "Escape") readingRef.current?.blur();
                event.stopPropagation();
              }}
            >
              <span {...stylex.props(s.badge)}>{`#${selected.index + 1}`}</span>
              <TextInput
                ref={readingRef}
                size="dense"
                aria-label="Region OCR text"
                placeholder="Enter text…"
                value={reading}
                disabled={saving}
                xstyle={s.reading}
                onChange={(event) =>
                  dispatch({
                    type: "set_reading_text",
                    index: selected.index,
                    text: event.target.value,
                  })
                }
              />
              {reading !== "" ? (
                <IconButton
                  label="Clear text"
                  size="2xs"
                  disabled={saving}
                  onClick={() =>
                    dispatch({ type: "clear_reading", index: selected.index })
                  }
                >
                  <X size={11} />
                </IconButton>
              ) : null}
              {confidence === null ? null : (
                <span {...stylex.props(s.score)}>
                  {confidenceBadge(confidence)}
                </span>
              )}
            </div>
          ) : null}
          {eraserHint ? (
            <div className="nodrag nopan" {...stylex.props(s.pill)}>
              <span {...stylex.props(s.hint)}>
                Eraser: click any region to remove
              </span>
              <IconButton
                label="Done"
                size="2xs"
                disabled={saving}
                onClick={() => dispatch({ type: "set_mode", mode: "select" })}
              >
                <X size={11} />
              </IconButton>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

type ShortcutSource = {
  readonly active: boolean;
  readonly state: TiffTextRegionsEditorState;
  readonly dispatch: React.Dispatch<TiffTextRegionsEditorAction>;
  readonly confirmDiscard: boolean;
  readonly onCloseDiscard: () => void;
};

/**
 * Document-level editing keys: `⌘/Ctrl+Z`, `⌘/Ctrl+⇧+Z` and `Ctrl+Y`, `Delete`,
 * `M` for merge, `E` for the eraser, and `Escape` peeling one layer off at a time.
 *
 * They live on the document because the tools are not focusable in order — a person
 * is dragging a vertex, not tabbing through a form — and they listen only while this
 * surface is the frontmost one, so a card behind a fullscreen modal cannot answer the
 * same `⌘Z` twice. Anything typed into a field is none of its business.
 */
function useRegionEditShortcuts({
  active,
  state,
  dispatch,
  confirmDiscard,
  onCloseDiscard,
}: ShortcutSource): void {
  React.useEffect(() => {
    if (!active) return;
    function onKeyDown(event: KeyboardEvent): void {
      if (isTextEntry(event.target)) return;

      const key = event.key.toLowerCase();
      const modifier = event.metaKey || event.ctrlKey;
      if (modifier && key === "z" && !event.shiftKey) {
        event.preventDefault();
        dispatch({ type: "undo" });
        return;
      }
      if (modifier && ((key === "z" && event.shiftKey) || key === "y")) {
        event.preventDefault();
        dispatch({ type: "redo" });
        return;
      }

      if (event.key === "Delete" || event.key === "Backspace") {
        // Several regions are in hand, so the key means "these", all of them, in the
        // one undo step that a shift-clicking person expects to be able to undo.
        if (state.selectedRegions.length > 1) {
          event.preventDefault();
          dispatch({ type: "delete_selected_region" });
          return;
        }
        const selection = state.selection;
        const selected = selectedRegion(state);
        // No selection, or one left pointing past the end by someone else's delete:
        // there is nothing here to eat, so the key belongs to the page.
        if (selection === null || selected === null) return;
        event.preventDefault();
        // A corner is the finer thing to remove, and only when the polygon can
        // survive losing it: a triangle with one corner gone is a line.
        if (
          selection.vertex !== null &&
          selected.region.polygon.length > MIN_POLYGON_VERTICES
        ) {
          dispatch({
            type: "delete_vertex",
            region: selected.index,
            vertex: selection.vertex,
          });
          return;
        }
        dispatch({ type: "delete_selected_region" });
        return;
      }

      // The single-letter tools are bare: with `⌘`, `Ctrl`, or `Alt` on them the
      // keystroke belongs to the browser or the shell, and this surface lets it go.
      const bare = !event.metaKey && !event.ctrlKey && !event.altKey;
      if (bare && key === "m" && state.selectedRegions.length >= 2) {
        event.preventDefault();
        dispatch({ type: "merge_selected_regions" });
        return;
      }
      if (bare && key === "e") {
        event.preventDefault();
        dispatch({
          type: "set_mode",
          mode: state.mode === "eraser" ? "select" : "eraser",
        });
        return;
      }

      if (event.key !== "Escape") return;
      // Each of these takes the key for itself, so one Escape undoes exactly one
      // thing and never closes the modal that sits around the editor.
      if (confirmDiscard) {
        event.preventDefault();
        event.stopPropagation();
        onCloseDiscard();
      } else if (state.draft !== null) {
        event.preventDefault();
        event.stopPropagation();
        dispatch({ type: "cancel_draft" });
      } else if (state.selection !== null) {
        event.preventDefault();
        event.stopPropagation();
        dispatch({ type: "clear_selection" });
      } else if (state.mode !== "select") {
        event.preventDefault();
        event.stopPropagation();
        dispatch({ type: "set_mode", mode: "select" });
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [active, state, dispatch, confirmDiscard, onCloseDiscard]);
}
