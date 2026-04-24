/**
 * Files & folders API client.
 *
 * Uses apiFetch for JSON endpoints and a dedicated XHR implementation for
 * uploads (so we can observe real upload progress — fetch() has no upload
 * progress events). Upload retries once on 401 via the shared requestRefresh
 * helper from lib/api.ts.
 */
import { apiFetch, ApiError, requestRefresh } from "@/lib/api";
import { useAuthStore } from "@/features/auth/store";
import type {
  FileItem,
  FileListResponse,
  FolderDeleteResult,
  FolderDownloadUrlResponse,
  FolderItem,
  FolderListResponse,
  SignedUrlMode,
  SignedUrlResponse,
  StorageUsage,
} from "./types";

export type ListFilesParams = {
  page?: number;
  page_size?: number;
  /** Search spans the whole tree regardless of folder scope. */
  q?: string;
  /** null / undefined → root. */
  folder_id?: string | null;
};

export type UploadProgress = {
  loaded: number;
  total: number;
  /** 0–100 */
  percent: number;
};

export type UploadOptions = {
  onProgress?: (p: UploadProgress) => void;
  signal?: AbortSignal;
  /** Target folder id. `null`/`undefined` means upload to root. */
  folderId?: string | null;
  /**
   * Relative directory path for folder uploads (from webkitRelativePath,
   * minus the filename). The server materializes missing folders in
   * this chain, nested under `folderId` if provided, otherwise at root.
   */
  relativePath?: string;
};

function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

export const filesApi = {
  list(params: ListFilesParams = {}): Promise<FileListResponse> {
    const qs = buildQuery({
      page: params.page ?? 1,
      page_size: params.page_size ?? 50,
      q: params.q,
      folder_id: params.folder_id ?? undefined,
    });
    return apiFetch<FileListResponse>(`/api/files${qs}`, { method: "GET" });
  },

  get(id: string): Promise<FileItem> {
    return apiFetch<FileItem>(`/api/files/${id}`, { method: "GET" });
  },

  remove(id: string): Promise<void> {
    return apiFetch<void>(`/api/files/${id}`, { method: "DELETE" });
  },

  signedUrl(id: string, mode: SignedUrlMode): Promise<SignedUrlResponse> {
    const qs = buildQuery({ mode });
    return apiFetch<SignedUrlResponse>(`/api/files/${id}/signed-url${qs}`, {
      method: "GET",
    });
  },

  storageUsage(): Promise<StorageUsage> {
    return apiFetch<StorageUsage>(`/api/storage/usage`, { method: "GET" });
  },

  upload(file: File, opts: UploadOptions = {}): Promise<FileItem> {
    return uploadWithXHR(file, opts);
  },
};

export const foldersApi = {
  list(parentId?: string | null): Promise<FolderListResponse> {
    const qs = buildQuery({ parent_id: parentId ?? undefined });
    return apiFetch<FolderListResponse>(`/api/folders${qs}`, { method: "GET" });
  },

  create(payload: { name: string; parent_id?: string | null }): Promise<FolderItem> {
    // `apiFetch` handles JSON.stringify + Content-Type itself — pass the
    // raw object. Passing a pre-stringified body would get re-stringified
    // and arrive at the server as a JSON string (not an object), which
    // Ninja rejects with 422 Unprocessable Entity.
    return apiFetch<FolderItem>(`/api/folders`, {
      method: "POST",
      body: {
        name: payload.name,
        parent_id: payload.parent_id ?? null,
      },
    });
  },

  remove(id: string): Promise<FolderDeleteResult> {
    return apiFetch<FolderDeleteResult>(`/api/folders/${id}`, {
      method: "DELETE",
    });
  },

  downloadUrl(id: string): Promise<FolderDownloadUrlResponse> {
    return apiFetch<FolderDownloadUrlResponse>(
      `/api/folders/${id}/download-url`,
      { method: "GET" },
    );
  },
};

/**
 * XHR-based upload with progress events. On 401, calls requestRefresh() once
 * (coalesced with any concurrent refresh in flight) and retries.
 *
 * Folder placement: if `opts.folderId` is set, the file is placed in that
 * folder. If `opts.relativePath` is set, the server creates any missing
 * intermediate folders (under `folderId` if given, else at root) and
 * places the file at the leaf. Both may be combined.
 */
function uploadWithXHR(file: File, opts: UploadOptions): Promise<FileItem> {
  const send = (token: string | null): Promise<{ status: number; body: unknown; contentType: string }> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/files", true);
      xhr.withCredentials = true;
      xhr.responseType = "text";
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

      if (opts.onProgress && xhr.upload) {
        xhr.upload.onprogress = (e) => {
          if (!e.lengthComputable) return;
          const percent = Math.round((e.loaded / e.total) * 100);
          opts.onProgress!({ loaded: e.loaded, total: e.total, percent });
        };
      }

      xhr.onload = () => {
        const contentType = xhr.getResponseHeader("Content-Type") ?? "";
        let body: unknown = xhr.responseText;
        if (contentType.includes("application/json")) {
          try {
            body = JSON.parse(xhr.responseText);
          } catch {
            // fall through with text body
          }
        }
        resolve({ status: xhr.status, body, contentType });
      };

      xhr.onerror = () => reject(new ApiError(0, "NETWORK_ERROR", "Network error during upload"));
      xhr.onabort = () => reject(new ApiError(0, "ABORTED", "Upload aborted"));

      if (opts.signal) {
        if (opts.signal.aborted) {
          xhr.abort();
          return;
        }
        opts.signal.addEventListener("abort", () => xhr.abort(), { once: true });
      }

      const form = new FormData();
      form.append("file", file, file.name);
      if (opts.folderId) {
        form.append("folder_id", opts.folderId);
      }
      if (opts.relativePath) {
        form.append("relative_path", opts.relativePath);
      }
      xhr.send(form);
    });

  const run = async (): Promise<FileItem> => {
    const token = useAuthStore.getState().accessToken;
    let result = await send(token);

    if (result.status === 401) {
      const newToken = await requestRefresh();
      if (!newToken) {
        useAuthStore.getState().clear();
        throw new ApiError(401, "UNAUTHORIZED", "Session expired");
      }
      result = await send(newToken);
    }

    if (result.status >= 200 && result.status < 300) {
      return result.body as FileItem;
    }

    const b = result.body;
    const code =
      (b && typeof b === "object" && "code" in b && (b as { code: string }).code) || "HTTP_ERROR";
    const message =
      (b && typeof b === "object" && "message" in b && (b as { message: string }).message) ||
      "Upload failed";
    throw new ApiError(result.status, String(code), String(message), b);
  };

  return run();
}
