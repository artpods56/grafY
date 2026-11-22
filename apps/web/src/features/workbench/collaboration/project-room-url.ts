import { API_BASE } from "@/lib/api/client";

/** Same-origin WebSocket URL for a workspace-scoped Project room. */
export function projectRoomWebSocketUrl(
  workspaceId: string,
  projectId: string,
): string {
  const path =
    `${API_BASE}/v1/workspaces/${encodeURIComponent(workspaceId)}` +
    `/projects/${encodeURIComponent(projectId)}/room`;
  if (typeof window === "undefined") {
    return path;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}
