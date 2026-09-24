export const API_BASE = "/api";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const MAX_ERROR_BODY_CHARACTERS = 4_096;
const MAX_ERROR_DETAIL_CHARACTERS = 2_048;
const MAX_ERROR_TOKEN_READ_AHEAD = 4_096;

const unauthorizedListeners = new Set<() => void>();

export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

export function readBrowserCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;

  const prefix = `${name}=`;
  for (const segment of document.cookie.split(";")) {
    const cookie = segment.trim();
    if (!cookie.startsWith(prefix)) continue;
    const value = cookie.slice(prefix.length);
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }
  return undefined;
}

function isUnsafeMethod(method: string): boolean {
  return !SAFE_METHODS.has(method.toUpperCase());
}

function redactSensitiveValue(
  value: string,
  sensitiveValue: string | undefined,
): string {
  if (!sensitiveValue) return value;
  return value.replaceAll(sensitiveValue, "[REDACTED]");
}

function boundedDetail(value: string, csrfToken: string | undefined): string {
  return redactSensitiveValue(value, csrfToken).slice(
    0,
    MAX_ERROR_DETAIL_CHARACTERS,
  );
}

async function readBoundedResponseText(
  response: Response,
  csrfToken: string | undefined,
): Promise<string> {
  if (!response.body) {
    return "";
  }

  const reader = response.body.getReader();
  const maxBytes =
    MAX_ERROR_BODY_CHARACTERS +
    Math.min(csrfToken?.length ?? 0, MAX_ERROR_TOKEN_READ_AHEAD);
  const decoder = new TextDecoder();
  let bytesRead = 0;
  let streamComplete = false;
  let text = "";

  try {
    while (bytesRead < maxBytes) {
      const result = await reader.read();
      if (result.done) {
        streamComplete = true;
        break;
      }

      const remainingBytes = maxBytes - bytesRead;
      const chunk =
        result.value.byteLength > remainingBytes
          ? result.value.subarray(0, remainingBytes)
          : result.value;
      text += decoder.decode(chunk, { stream: true });
      bytesRead += chunk.byteLength;
      if (chunk.byteLength < result.value.byteLength) break;
    }
    text += decoder.decode();
    return text;
  } finally {
    if (!streamComplete) {
      try {
        await reader.cancel();
      } catch {
        // The response is already being discarded.
      }
    }
  }
}

async function responseErrorDetail(
  response: Response,
  csrfToken: string | undefined,
): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const body = await readBoundedResponseText(response, csrfToken);
    if (!body) return fallback;

    let detail = body;
    try {
      const payload: unknown = JSON.parse(body);
      if (typeof payload === "string") {
        detail = payload;
      } else if (
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof payload.detail === "string"
      ) {
        detail = payload.detail;
      }
    } catch {
      // Keep the bounded response text when it is not JSON.
    }
    return boundedDetail(detail, csrfToken);
  } catch {
    return fallback;
  }
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
}

/**
 * Send raw bytes to an upload target the API handed back.
 *
 * `kind: "api"` targets are owned by this origin: send the session cookie and
 * CSRF token. `kind: "storage"` targets are self-authorizing signed URLs: send
 * only the required signed headers, even when the hostname is same-origin.
 */
export async function putUploadBytes(
  target: {
    kind: "api" | "storage";
    url: string;
    headers?: Readonly<Record<string, string>>;
  },
  bytes: BodyInit,
  contentType: string,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    ...(target.headers ?? {}),
  };
  if (contentType && headers["Content-Type"] === undefined) {
    headers["Content-Type"] = contentType;
  }

  if (target.kind === "api") {
    const csrfToken = readBrowserCookie("grafy_csrf");
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    const response = await fetch(target.url, {
      method: "PUT",
      headers,
      body: bytes,
      credentials: "same-origin",
      signal,
      redirect: "error",
    });
    if (!response.ok) {
      throw new ApiError(
        response.status,
        await responseErrorDetail(response, csrfToken),
      );
    }
    return;
  }

  const response = await fetch(target.url, {
    method: "PUT",
    headers,
    body: bytes,
    credentials: "omit",
    signal,
    redirect: "error",
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      await responseErrorDetail(response, undefined),
    );
  }
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, signal } = options;
  const normalizedMethod = method.toUpperCase();
  const csrfToken = isUnsafeMethod(normalizedMethod)
    ? readBrowserCookie("grafy_csrf")
    : undefined;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const init: RequestInit = {
    method: normalizedMethod,
    headers,
    credentials: "same-origin",
    signal,
  };
  if (body !== undefined) {
    if (typeof FormData !== "undefined" && body instanceof FormData) {
      init.body = body;
    } else {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }

  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    if (res.status === 401 && path !== "/v1/auth/session") {
      for (const listener of unauthorizedListeners) listener();
    }
    const detail = await responseErrorDetail(res, csrfToken);
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}
