/**
 * Which Workspace Library artifacts the side panel holds selected at once.
 *
 * A Library row answers three different clicks, and all three need the same
 * thing: the set of selected artifacts and the row a shift-click measures from.
 * The set is the model here and the tree only ever reads it, so a row, a context
 * menu and the Delete key cannot each keep their own idea of what is selected —
 * the bug that shows up the first time a refresh drops a row out from under a
 * selection or a filter hides it.
 *
 * Two rules the callers depend on:
 * - A shift range runs over the artifacts the tree shows RIGHT NOW, in the order
 *   it shows them, so a collapsed folder or an active filter narrows the range
 *   instead of spanning rows the user cannot see. Folders are not selectable and
 *   are not in that list at all.
 * - Ids the Library no longer has are dropped, never held onto hoping a later
 *   refresh brings them back.
 */

/** How a click or key gesture changes the selection. */
export type LibrarySelectionGesture = "plain" | "toggle" | "range";

export type LibrarySelection = {
  /** Selected artifact ids, oldest first. Never holds the same id twice. */
  readonly ids: readonly string[];
  /** The row a shift range measures from, or null when no row was clicked. */
  readonly anchor: string | null;
};

export const emptyLibrarySelection: LibrarySelection = {
  ids: [],
  anchor: null,
};

export function isLibraryItemSelected(
  selection: LibrarySelection,
  artifactId: string,
): boolean {
  return selection.ids.includes(artifactId);
}

/**
 * The gesture behind a pointer click on a row.
 *
 * Cmd on macOS, Ctrl everywhere else toggles one row; shift takes the range
 * measured from the anchor. Both modifiers at once means the range, because the
 * anchor is already the row the user picked out and shift is the one that says
 * "and everything up to there".
 */
export function libraryClickGesture(event: {
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
}): LibrarySelectionGesture {
  if (event.shiftKey) return "range";
  if (event.metaKey || event.ctrlKey) return "toggle";
  return "plain";
}

/**
 * Apply one gesture.
 *
 * `visible` is every selectable artifact id in the order the tree shows it now;
 * the caller derives it from the same flattened rows the tree rendered, so a
 * range never reaches past a collapsed folder or a filtered-out row.
 */
export function applyLibrarySelection(input: {
  selection: LibrarySelection;
  artifactId: string;
  gesture: LibrarySelectionGesture;
  visible: readonly string[];
}): LibrarySelection {
  const { selection, artifactId, gesture, visible } = input;

  if (gesture === "plain") {
    return { ids: [artifactId], anchor: artifactId };
  }

  if (gesture === "toggle") {
    const ids = selection.ids.includes(artifactId)
      ? selection.ids.filter((id) => id !== artifactId)
      : [...selection.ids, artifactId];
    if (ids.length === 0) return emptyLibrarySelection;
    // The clicked row becomes the anchor even when it was taken out of the
    // selection, so a shift click afterwards measures from the last row the user
    // named rather than from one they stopped naming three rows ago.
    return { ids, anchor: artifactId };
  }

  // A range with nothing to measure from — no anchor, or an anchor the tree no
  // longer shows — behaves like a plain click rather than selecting everything.
  const from =
    selection.anchor === null ? -1 : visible.indexOf(selection.anchor);
  const to = visible.indexOf(artifactId);
  if (from < 0 || to < 0) {
    return { ids: [artifactId], anchor: artifactId };
  }
  const [start, end] = from <= to ? [from, to] : [to, from];
  return { ids: visible.slice(start, end + 1), anchor: selection.anchor };
}

/**
 * Drop selected artifacts the Library no longer lists.
 *
 * Returns the same object when nothing changed, so a refresh that deleted
 * nothing cannot re-render every row or reset a selection the user is working
 * through. An anchor that vanished is forgotten: the next shift-click then
 * starts a range from wherever the next plain click lands.
 */
export function pruneLibrarySelection(
  selection: LibrarySelection,
  existingIds: ReadonlySet<string>,
): LibrarySelection {
  const ids = selection.ids.filter((id) => existingIds.has(id));
  if (ids.length === 0) {
    return selection.ids.length === 0 && selection.anchor === null
      ? selection
      : emptyLibrarySelection;
  }
  const anchor =
    selection.anchor !== null && existingIds.has(selection.anchor)
      ? selection.anchor
      : ids.length === 1
        ? (ids[0] ?? null)
        : null;
  if (
    anchor === selection.anchor &&
    ids.length === selection.ids.length &&
    ids.every((id, index) => id === selection.ids[index])
  ) {
    return selection;
  }
  return { ids, anchor };
}

/**
 * The selection without the listed artifacts, anchor included. The same object
 * comes back when none of them were selected.
 */
export function removeFromLibrarySelection(
  selection: LibrarySelection,
  artifactIds: readonly string[],
): LibrarySelection {
  const gone = new Set(artifactIds);
  const ids = selection.ids.filter((id) => !gone.has(id));
  if (ids.length === selection.ids.length) return selection;
  if (ids.length === 0) return emptyLibrarySelection;
  return {
    ids,
    anchor:
      selection.anchor !== null && !gone.has(selection.anchor)
        ? selection.anchor
        : null,
  };
}

/**
 * The selected artifacts in the order the tree shows them, then any selected id
 * the tree does not show.
 *
 * Deleting and dragging both work in tree order so what the user sees top to
 * bottom is what gets deleted and what lands on the canvas, whatever order they
 * clicked the rows in.
 */
export function orderedLibrarySelection(
  selection: LibrarySelection,
  visible: readonly string[],
): string[] {
  const selected = new Set(selection.ids);
  const shown = visible.filter((id) => selected.has(id));
  const shownSet = new Set(shown);
  return [...shown, ...selection.ids.filter((id) => !shownSet.has(id))];
}

/** How much of one refusal sentence a summary is allowed to spend on a row. */
const REFUSAL_DETAIL_LIMIT = 48;

/**
 * What a bulk delete says when some artifacts refused.
 *
 * One sentence for the whole batch, naming what is still there and why, because
 * a dialog that deleted four of five and said nothing would leave the user to
 * find the fifth by hand. An empty batch of refusals returns null: a delete that
 * landed has nothing to say for itself.
 */
export function libraryBulkDeleteSummary(
  deletedCount: number,
  refused: readonly { name: string; detail: string }[],
): string | null {
  if (refused.length === 0) return null;
  const head =
    deletedCount > 0 ? `Deleted ${deletedCount}. ` : "Nothing deleted. ";
  const [only] = refused;
  if (refused.length === 1 && only) {
    return `${head}${refused.length} ${lowerFirstSentence(only.detail)}`;
  }
  const listed = refused
    .slice(0, 3)
    .map((entry) => `${entry.name}: ${shortenRefusalDetail(entry.detail)}`);
  if (refused.length > 3) listed.push(`${refused.length - 3} more`);
  return `${head}${refused.length} refused — ${listed.join("; ")}.`;
}

function lowerFirstSentence(text: string): string {
  const trimmed = text.trim();
  return trimmed.length === 0
    ? trimmed
    : `${trimmed[0]!.toLowerCase()}${trimmed.slice(1)}`;
}

function shortenRefusalDetail(text: string): string {
  const trimmed = text.trim().replace(/\.$/, "");
  if (trimmed.length <= REFUSAL_DETAIL_LIMIT) return trimmed;
  return `${trimmed.slice(0, REFUSAL_DETAIL_LIMIT - 1)}…`;
}

/** `"3 selected"`, or null when there is nothing worth announcing. */
export function librarySelectionSummary(
  selection: LibrarySelection,
): string | null {
  return selection.ids.length >= 2 ? `${selection.ids.length} selected` : null;
}
