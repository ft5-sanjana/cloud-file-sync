/**
 * Typed fetch wrapper for the Cloud File Sync API.
 *
 * Responsibilities:
 * - Attach `Authorization: Bearer <accessToken>` from the Zustand auth store.
 * - Set `X-Requested-With: XMLHttpRequest` (CSRF mitigation for state-changing routes).
 * - Auto-refresh on 401 by calling POST /api/auth/refresh (one retry).
 * - Propagate a typed ApiError with code + message for the UI to surface.
 */
import { useAuthStore } from "@/features/auth/store";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type FetchOptions = Omit<RequestInit, "body" | "headers"> & {
  body?: unknown;
  headers?: Record<string, string>;
  skipAuth?: boolean;
  skipRefresh?: boolean;
  /** Pass a File/FormData directly without JSON serialization. */
  raw?: boolean;
};

const REFRESH_PATH = "/api/auth/refresh";

let refreshInFlight: Promise<string | null> | null = null;

/**
 * Single-flight refresh. Exported so callers outside apiFetch (e.g. XHR-based
 * upload with progress) can participate in the same coalesced refresh.
 */
export async function requestRefresh(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(REFRESH_PATH, {
        method: "POST",
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!res.ok) return null;
      const data = (await res.json()) as { access: string };
      useAuthStore.getState().setAccessToken(data.access);
      return data.access;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const { body, headers = {}, skipAuth, skipRefresh, raw, ...rest } = options;

  const buildHeaders = (token: string | null): Record<string, string> => {
    const h: Record<string, string> = {
      "X-Requested-With": "XMLHttpRequest",
      ...headers,
    };
    if (!raw && body !== undefined) h["Content-Type"] = "application/json";
    if (!skipAuth && token) h["Authorization"] = `Bearer ${token}`;
    return h;
  };

  const buildBody = (): BodyInit | null | undefined => {
    if (body === undefined) return undefined;
    if (raw) return body as BodyInit;
    return JSON.stringify(body);
  };

  const token = useAuthStore.getState().accessToken;

  let res = await fetch(path, {
    ...rest,
    credentials: "include",
    headers: buildHeaders(token),
    body: buildBody(),
  });

  // Auto-refresh on 401 once, then retry the original request.
  if (res.status === 401 && !skipAuth && !skipRefresh) {
    const newToken = await requestRefresh();
    if (newToken) {
      res = await fetch(path, {
        ...rest,
        credentials: "include",
        headers: buildHeaders(newToken),
        body: buildBody(),
      });
    } else {
      useAuthStore.getState().clear();
    }
  }

  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("Content-Type") ?? "";
  const data = contentType.includes("application/json")
    ? await res.json()
    : await res.text();

  if (!res.ok) {
    const code = (data && typeof data === "object" && "code" in data && (data as { code: string }).code) || "HTTP_ERROR";
    const message = (data && typeof data === "object" && "message" in data && (data as { message: string }).message) || res.statusText || "Request failed";
    throw new ApiError(res.status, String(code), String(message), data);
  }

  return data as T;
}
