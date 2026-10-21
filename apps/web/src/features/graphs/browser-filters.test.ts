import { describe, expect, it } from "vitest";

import {
  DEFAULT_GRAPH_BROWSER_VIEW,
  GRAPH_BROWSER_LOCATION_PARAM,
  GRAPH_BROWSER_QUERY_PARAM,
  GRAPH_BROWSER_VIEW_PARAM,
  patchGraphBrowserFilters,
  parseGraphBrowserQuery,
  parseGraphBrowserView,
  readGraphBrowserFilters,
  readRequestedLocation,
  searchForChosenLocation,
  serializeGraphBrowserSearch,
} from "./browser-filters";

function search(value: string): URLSearchParams {
  return new URLSearchParams(value.startsWith("?") ? value.slice(1) : value);
}

describe("graph browser address filters", () => {
  it("reads the defaults from an address that names none of them", () => {
    expect(readGraphBrowserFilters(search(""))).toEqual({
      query: "",
      view: DEFAULT_GRAPH_BROWSER_VIEW,
    });
    expect(readGraphBrowserFilters(search("?page=3"))).toEqual({
      query: "",
      view: "recent",
    });
  });

  it("reads a shared address", () => {
    expect(
      readGraphBrowserFilters(search("?q=Invoice%20intake&view=all")),
    ).toEqual({ query: "Invoice intake", view: "all" });
  });

  it("keeps the search text exactly as the person typed it", () => {
    // Case and inner spacing decide the matches, so neither is normalised away.
    expect(parseGraphBrowserQuery("  In voice ")).toBe("  In voice ");
    expect(
      search(`?${GRAPH_BROWSER_QUERY_PARAM}=In%20voice`).get(
        GRAPH_BROWSER_QUERY_PARAM,
      ),
    ).toBe("In voice");
  });

  it("falls back to the default for a view it does not offer", () => {
    for (const value of ["archive", "Recent", "", "all;drop"]) {
      expect(parseGraphBrowserView(value)).toBe("recent");
    }
    expect(parseGraphBrowserView("all")).toBe("all");
    expect(readGraphBrowserFilters(search("?view=archive")).view).toBe(
      "recent",
    );
  });

  it("bounds free-form search text instead of trusting the address", () => {
    const long = "a".repeat(5_000);
    expect(parseGraphBrowserQuery(long)).toHaveLength(200);
    expect(
      readGraphBrowserFilters(new URLSearchParams({ q: long })).query,
    ).toHaveLength(200);
    expect(parseGraphBrowserQuery(null)).toBe("");
  });

  it("writes a filter and drops it again once it is back on its default", () => {
    const typed = patchGraphBrowserFilters(search(""), { query: "inv" });
    expect(typed.toString()).toBe("q=inv");

    const cleared = patchGraphBrowserFilters(typed, { query: "" });
    expect(cleared.toString()).toBe("");
    expect(cleared.has(GRAPH_BROWSER_QUERY_PARAM)).toBe(false);
  });

  it("leaves the default view out of the address", () => {
    expect(
      patchGraphBrowserFilters(search(""), { view: "all" }).toString(),
    ).toBe("view=all");
    expect(
      patchGraphBrowserFilters(search("?view=all"), {
        view: "recent",
      }).toString(),
    ).toBe("");
  });

  it("cleans a view it does not offer out of the next address", () => {
    const patched = patchGraphBrowserFilters(search("?view=archive"), {
      query: "intake",
    });
    expect(patched.has(GRAPH_BROWSER_VIEW_PARAM)).toBe(false);
    expect(patched.toString()).toBe("q=intake");
  });

  it("carries every parameter it does not own", () => {
    const patched = patchGraphBrowserFilters(
      search("?utm_source=email&flag=1&view=all"),
      { query: "intake" },
    );
    expect(patched.toString()).toBe(
      "utm_source=email&flag=1&view=all&q=intake",
    );
  });

  it("keeps the location hint it was not asked to change", () => {
    // Only an entry route consumes `location`; on a browser it is someone
    // else's parameter and travels untouched.
    const patched = patchGraphBrowserFilters(search("?location=atlas"), {
      query: "intake",
    });
    expect(patched.get(GRAPH_BROWSER_LOCATION_PARAM)).toBe("atlas");
  });

  it("reads a requested location only when the address really names one", () => {
    expect(readRequestedLocation(search("?location=atlas"))).toBe("atlas");
    expect(readRequestedLocation(search("?location=%20atlas%20"))).toBe(
      "atlas",
    );
    for (const value of ["", "?location=", "?location=%20", "?page=2"]) {
      expect(readRequestedLocation(search(value))).toBeNull();
    }
  });

  it("hands the filters to the chosen location without the entry hint", () => {
    const carried = searchForChosenLocation(
      search("?location=ghost&q=intake&view=all&utm_source=email"),
    );
    expect(carried.toString()).toBe("q=intake&view=all&utm_source=email");
  });

  it("omits the question mark when nothing is left to carry", () => {
    expect(serializeGraphBrowserSearch(search(""))).toBe("");
    expect(
      serializeGraphBrowserSearch(
        searchForChosenLocation(search("?location=atlas")),
      ),
    ).toBe("");
    expect(
      serializeGraphBrowserSearch(search(`?${GRAPH_BROWSER_QUERY_PARAM}=a`)),
    ).toBe("?q=a");
  });
});
