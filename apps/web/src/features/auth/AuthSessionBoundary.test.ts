import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import { sessionFailureKind } from "./AuthSessionBoundary";

describe("initial session failure classification", () => {
  it("keeps true 401 signed out while treating outages as unavailable", () => {
    expect(sessionFailureKind(new ApiError(401, "unauthorized"))).toBe(
      "signed-out",
    );
    expect(sessionFailureKind(new ApiError(500, "server unavailable"))).toBe(
      "unavailable",
    );
    expect(sessionFailureKind(new TypeError("network unavailable"))).toBe(
      "unavailable",
    );
  });
});
