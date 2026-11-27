import { API_BASE, request } from "./client";
import type {
  AdminOperatorStatus,
  FeedbackReceipt,
  FeedbackReport,
  FeedbackReportSubmission,
  FeedbackReportUpdate,
  FeedbackStatus,
} from "./contract";

export function submitFeedback(
  report: FeedbackReportSubmission,
  screenshot: Blob | null,
) {
  const form = new FormData();
  form.set("report", JSON.stringify(report));
  if (screenshot) {
    form.set(
      "screenshot",
      screenshot,
      screenshot.type === "image/jpeg" ? "screenshot.jpg" : "screenshot.png",
    );
  }
  return request<FeedbackReceipt>("POST", "/v1/feedback", { body: form });
}

export function getOperatorStatus() {
  return request<AdminOperatorStatus>("GET", "/v1/admin/operator");
}

/** One page of reports, newest first. Also the SWR key: the global fetcher GETs it. */
export function feedbackReportsPath(
  status: FeedbackStatus | null,
  before: string | null,
  limit: number,
): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  if (before) params.set("before", before);
  return `/v1/admin/feedback?${params.toString()}`;
}

export function updateFeedbackReport(
  reportId: string,
  body: FeedbackReportUpdate,
) {
  return request<FeedbackReport>(
    "PATCH",
    `/v1/admin/feedback/${encodeURIComponent(reportId)}`,
    { body },
  );
}

export function deleteFeedbackReport(reportId: string) {
  return request<void>(
    "DELETE",
    `/v1/admin/feedback/${encodeURIComponent(reportId)}`,
  );
}

/** Same-origin, cookie-authenticated, so an `<img>` can load it directly. */
export function feedbackScreenshotUrl(reportId: string): string {
  return `${API_BASE}/v1/admin/feedback/${encodeURIComponent(reportId)}/screenshot`;
}
