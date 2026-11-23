import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { BRAND_ICON_SRC, BRAND_LOGO_SRC } from "./brand";
import { ThresholdStatus } from "./threshold-status";

describe("ThresholdStatus", () => {
  it("uses the animated brand mark while loading", () => {
    const markup = renderToStaticMarkup(
      <ThresholdStatus
        title="Loading graph location"
        detail="Checking your current access…"
        loading
      />,
    );
    // The loader is the icon plus status semantics; the wordmark is absent.
    expect(markup).toContain(BRAND_ICON_SRC);
    expect(markup).toContain('role="status"');
    expect(markup).toContain('aria-label="Loading graph location"');
    expect(markup).toContain("Loading graph location");
    expect(markup).toContain("Checking your current access…");
    expect(markup).not.toContain(BRAND_LOGO_SRC);
  });

  it("uses the wordmark and action once the route has settled", () => {
    const markup = renderToStaticMarkup(
      <ThresholdStatus
        title="Graph location not found"
        detail="This graph location is not available to your account."
        action={<a href="/graphs">Return to graphs</a>}
      />,
    );
    expect(markup).toContain(BRAND_LOGO_SRC);
    expect(markup).toContain("Return to graphs");
    expect(markup).not.toContain(BRAND_ICON_SRC);
    expect(markup).not.toContain('role="status"');
  });

  it("renders the message the caller passed", () => {
    const markup = renderToStaticMarkup(
      <ThresholdStatus
        title="Sign in"
        detail="Your graphs and Team locations are available after authentication."
      />,
    );
    expect(markup).toContain("<h1");
    expect(markup).toContain("Sign in");
    expect(markup).toContain("Your graphs and Team locations are available");
  });
});
