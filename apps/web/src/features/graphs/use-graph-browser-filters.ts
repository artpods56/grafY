"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  parseGraphBrowserQuery,
  patchGraphBrowserFilters,
  readGraphBrowserFilters,
  serializeGraphBrowserSearch,
  type GraphBrowserFilters,
  type GraphBrowserView,
} from "./browser-filters";

export interface GraphBrowserFiltersState {
  /** The search text the address holds; the list is filtered by this. */
  readonly query: string;
  /** The view the address holds. */
  readonly view: GraphBrowserView;
  /** Attach to the search field, and give it `defaultValue={query}`. */
  readonly searchFieldRef: React.RefObject<HTMLInputElement | null>;
  setQuery: (value: string) => void;
  setView: (value: GraphBrowserView) => void;
}

/**
 * Graph-browser filters that read the address and write it back.
 *
 * Every commit uses `router.replace`, so browsing a list does not leave a Back
 * step per keystroke; the address still changes in place, and reload, a shared
 * link, and Back/Forward all restore the same list.
 *
 * The search field is deliberately not a controlled input, and that is the
 * whole design. `router.replace` settles some milliseconds after the keystroke
 * that asked for it, so a field whose value comes from the address is a field
 * that can be written back to a value the person has already typed past: the
 * browser reports `syc` because React restored `sy` between two keystrokes. The
 * field keeps its own text — `defaultValue` for the first render, then the
 * person's own typing — and this hook only writes it when the *address* is what
 * moved:
 *
 * - the address arrives at the newest filter this page asked for, and the field
 *   does not already say it, so a control (Clear search, a view tab) changed the
 *   filter and the field follows it;
 * - the address arrives at an older ask of ours, which means a newer keystroke
 *   is still in flight and the field is ahead of it, so the field is left alone;
 * - the address arrives somewhere this page never asked for — reload, Back,
 *   Forward, a pasted link — and the address wins outright.
 *
 * `view` needs none of that: one click commits the value it names, and the tabs
 * read the address directly.
 */
export function useGraphBrowserFilters(): GraphBrowserFiltersState {
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const committed = React.useMemo(
    () => readGraphBrowserFilters(new URLSearchParams(search)),
    [search],
  );
  const searchFieldRef = React.useRef<HTMLInputElement | null>(null);
  /**
   * What this page asked the address to hold, and the searches it asked for in
   * order, oldest first. Null once the address agrees with the page.
   */
  const authoredRef = React.useRef<{
    filters: GraphBrowserFilters;
    queries: string[];
  } | null>(null);

  const write = React.useCallback(
    (patch: Partial<GraphBrowserFilters>) => {
      const authored = authoredRef.current;
      // Unrelated parameters come from the address; the filters come from what
      // the page last asked for, so a fast second write cannot undo the first.
      const next = patchGraphBrowserFilters(new URLSearchParams(search), {
        ...authored?.filters,
        ...patch,
      });
      const filters = readGraphBrowserFilters(next);
      authoredRef.current = {
        filters,
        queries: [...(authored?.queries ?? []), filters.query].slice(-8),
      };
      router.replace(`${pathname}${serializeGraphBrowserSearch(next)}`, {
        scroll: false,
      });
    },
    [pathname, router, search],
  );

  React.useEffect(() => {
    const authored = authoredRef.current;
    const index = authored?.queries.indexOf(committed.query) ?? -1;
    if (authored && index >= 0 && index < authored.queries.length - 1) {
      // An older ask of ours reached the address while a newer one is still on
      // its way. The field is ahead of both and must not be pulled back.
      authoredRef.current = {
        filters: authored.filters,
        queries: authored.queries.slice(index + 1),
      };
      return;
    }
    authoredRef.current = null;
    const field = searchFieldRef.current;
    if (field && field.value !== committed.query) field.value = committed.query;
  }, [committed.query, search]);

  const setQuery = React.useCallback(
    (value: string) => {
      write({ query: parseGraphBrowserQuery(value) });
    },
    [write],
  );

  const setView = React.useCallback(
    (view: GraphBrowserView) => {
      if (view === committed.view) return;
      write({ view });
    },
    [committed.view, write],
  );

  return {
    query: committed.query,
    view: committed.view,
    searchFieldRef,
    setQuery,
    setView,
  };
}
