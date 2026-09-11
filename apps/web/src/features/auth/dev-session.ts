import type { Session } from "@/lib/api/contract";

/**
 * Opt-in stand-in session so a sandbox exercise can render without an API and
 * without an SSO round trip.
 *
 * Set `NEXT_PUBLIC_GRAFY_DEV_SESSION=1` when starting the dev server. A
 * production build ignores the flag, so this can never replace real auth in a
 * deployed app.
 */
const DEV_SESSION_FLAG = "1";

export function sandboxSession(): Session | null {
  if (process.env.NODE_ENV === "production") return null;
  if (process.env.NEXT_PUBLIC_GRAFY_DEV_SESSION !== DEV_SESSION_FLAG) {
    return null;
  }
  return {
    id: "00000000-0000-4000-8000-000000000001",
    user_id: "00000000-0000-4000-8000-000000000002",
    created_at: "2026-01-01T00:00:00Z",
    expires_at: "2100-01-01T00:00:00Z",
    last_used_at: "2026-01-01T00:00:00Z",
    revoked_at: null,
    current: true,
    display_name: "Sandbox",
    email: "sandbox@example.invalid",
  };
}
