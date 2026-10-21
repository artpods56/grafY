/**
 * The URL contract for the graph browser's filter state.
 *
 * A filtered graph list is worth putting in the address because a person
 * reloads it, sends it to a teammate, and expects Back to give it back. Three
 * parameters own it, and each one leaves the address when it sits on its
 * default: `q` (search text), `view` (`recent`, or `all`), and `location` (a
 * workspace slug, read only by the `/` and `/graphs` entry routes that still
 * have to choose a workspace). Anything else in the address belongs to another
 * writer — an analytics tag, a return path — and travels through untouched.
 *
 * A slug is how an address names a location here, so that is what `location`
 * holds; the workspace id never appears in one.
 */

/** The views this surface offers. The union is derived from the list. */
export const GRAPH_BROWSER_VIEWS = ["recent", "all"] as const;

export type GraphBrowserView = (typeof GRAPH_BROWSER_VIEWS)[number];

export const DEFAULT_GRAPH_BROWSER_VIEW: GraphBrowserView = "recent";

export const GRAPH_BROWSER_QUERY_PARAM = "q";
export const GRAPH_BROWSER_VIEW_PARAM = "view";
export const GRAPH_BROWSER_LOCATION_PARAM = "location";

/** Search text is free-form, so it gets one bound rather than a choice list. */
const MAX_QUERY_LENGTH = 200;

export interface GraphBrowserFilters {
  /** Graph search text, kept exactly as typed so the input can echo it back. */
  readonly query: string;
  readonly view: GraphBrowserView;
}

function isGraphBrowserView(
  value: string | null | undefined,
): value is GraphBrowserView {
  return GRAPH_BROWSER_VIEWS.some((view) => view === value);
}

/** Search text from the address, shortened to the bound this surface accepts. */
export function parseGraphBrowserQuery(
  value: string | null | undefined,
): string {
  if (!value) return "";
  return value.length > MAX_QUERY_LENGTH
    ? value.slice(0, MAX_QUERY_LENGTH)
    : value;
}

/** A view name from the address; anything unrecognised reads as the default. */
export function parseGraphBrowserView(
  value: string | null | undefined,
): GraphBrowserView {
  return isGraphBrowserView(value) ? value : DEFAULT_GRAPH_BROWSER_VIEW;
}

/** The filters an address commits, with defaults filled in. */
export function readGraphBrowserFilters(
  search: URLSearchParams,
): GraphBrowserFilters {
  return {
    query: parseGraphBrowserQuery(search.get(GRAPH_BROWSER_QUERY_PARAM)),
    view: parseGraphBrowserView(search.get(GRAPH_BROWSER_VIEW_PARAM)),
  };
}

/**
 * Merge a patch into the filters held by `search`, dropping every parameter
 * this browser does not own into the result unchanged. A filter that returns
 * to its default is removed instead of written as `?view=recent`, so a browsed
 * address stays as short as the address that was shared.
 */
export function patchGraphBrowserFilters(
  search: URLSearchParams,
  patch: Partial<GraphBrowserFilters>,
): URLSearchParams {
  const current = readGraphBrowserFilters(search);
  const query =
    patch.query === undefined
      ? current.query
      : parseGraphBrowserQuery(patch.query);
  const view =
    patch.view === undefined ? current.view : parseGraphBrowserView(patch.view);

  const next = new URLSearchParams(search.toString());
  if (query) next.set(GRAPH_BROWSER_QUERY_PARAM, query);
  else next.delete(GRAPH_BROWSER_QUERY_PARAM);
  if (view === DEFAULT_GRAPH_BROWSER_VIEW)
    next.delete(GRAPH_BROWSER_VIEW_PARAM);
  else next.set(GRAPH_BROWSER_VIEW_PARAM, view);
  return next;
}

/** `?a=1` for a non-empty search, `""` for an empty one, so paths stay clean. */
export function serializeGraphBrowserSearch(search: URLSearchParams): string {
  const serialized = search.toString();
  return serialized ? `?${serialized}` : "";
}

/**
 * The location an entry route was asked to open, or `null` when the address
 * did not ask. A slug is a request, never a fact: the caller has to match it
 * against the locations the person can actually reach before using it.
 */
export function readRequestedLocation(search: URLSearchParams): string | null {
  const slug = search.get(GRAPH_BROWSER_LOCATION_PARAM)?.trim();
  return slug ? slug : null;
}

/**
 * The address to hand to the location a route settled on: the filters travel
 * with the person, the entry-only `location` hint does not.
 */
export function searchForChosenLocation(
  search: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams(search.toString());
  next.delete(GRAPH_BROWSER_LOCATION_PARAM);
  return next;
}
