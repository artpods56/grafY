import { describe, expect, it } from "vitest";

import { shouldRetryApiError } from "./providers";
import { ApiError } from "@/lib/api/client";

describe("SWR API retry policy", () => {
  it("does not retry authorization or not-found responses", () => {
    expect(shouldRetryApiError(new ApiError(401, "unauthorized"))).toBe(false);
    expect(shouldRetryApiError(new ApiError(403, "forbidden"))).toBe(false);
    expect(shouldRetryApiError(new ApiError(404, "missing"))).toBe(false);
  });

  it("keeps retries for transient API and network failures", () => {
    expect(shouldRetryApiError(new ApiError(408, "timeout"))).toBe(true);
    expect(shouldRetryApiError(new ApiError(503, "unavailable"))).toBe(true);
    expect(shouldRetryApiError(new TypeError("network unavailable"))).toBe(
      true,
    );
  });
});
