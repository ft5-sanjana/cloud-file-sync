/**
 * TanStack Query wrappers around filesApi. All cache keys live here so
 * invalidation is colocated with the queries they invalidate.
 */
"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/lib/api";
import {
  filesApi,
  foldersApi,
  type ListFilesParams,
  type UploadOptions,
  type UploadProgress,
} from "./api";
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

export const filesKeys = {
  all: ["files"] as const,
  list: (params: ListFilesParams = {}) => [...filesKeys.all, "list", params] as const,
  detail: (id: string) => [...filesKeys.all, "detail", id] as const,
  storage: () => ["storage", "usage"] as const,
};

export const foldersKeys = {
  all: ["folders"] as const,
  list: (parentId: string | null = null) =>
    [...foldersKeys.all, "list", parentId ?? "root"] as const,
};

export function useFiles(
  params: ListFilesParams = {},
  options?: Omit<UseQueryOptions<FileListResponse, ApiError>, "queryKey" | "queryFn">,
) {
  return useQuery<FileListResponse, ApiError>({
    queryKey: filesKeys.list(params),
    queryFn: () => filesApi.list(params),
    ...options,
  });
}

export function useStorageUsage(
  options?: Omit<UseQueryOptions<StorageUsage, ApiError>, "queryKey" | "queryFn">,
) {
  return useQuery<StorageUsage, ApiError>({
    queryKey: filesKeys.storage(),
    queryFn: () => filesApi.storageUsage(),
    ...options,
  });
}

export type UploadArgs = {
  file: File;
  onProgress?: UploadOptions["onProgress"];
  signal?: AbortSignal;
  /** Target folder id. Omit/undefined for root. */
  folderId?: string | null;
  /** Directory part of the relative path (folder upload). */
  relativePath?: string;
};

export function useUploadFile() {
  const qc = useQueryClient();
  return useMutation<FileItem, ApiError, UploadArgs>({
    mutationFn: ({ file, onProgress, signal, folderId, relativePath }) =>
      filesApi.upload(file, { onProgress, signal, folderId, relativePath }),
    onSuccess: (item) => {
      toast.success(`Uploaded ${item.name}`);
      qc.invalidateQueries({ queryKey: filesKeys.all });
      qc.invalidateQueries({ queryKey: foldersKeys.all });
      qc.invalidateQueries({ queryKey: filesKeys.storage() });
    },
    onError: (err) => {
      if (err.code !== "ABORTED") {
        toast.error(err.message || "Upload failed");
      }
    },
  });
}

export function useDeleteFile() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, { id: string; name?: string }>({
    mutationFn: ({ id }) => filesApi.remove(id),
    onSuccess: (_data, vars) => {
      toast.success(vars.name ? `Deleted ${vars.name}` : "File deleted");
      qc.invalidateQueries({ queryKey: filesKeys.all });
      qc.invalidateQueries({ queryKey: filesKeys.storage() });
    },
    onError: (err) => {
      // 409 FILE_BUSY — upload still streaming; user just needs to wait.
      // 502 STORAGE_PURGE_FAILED — server retries in background, but tell
      // the user their click didn't fully complete so they can retry.
      if (err.code === "FILE_BUSY") {
        toast.error("This file is still uploading. Try again in a moment.");
      } else if (err.code === "STORAGE_PURGE_FAILED") {
        toast.error(
          "Storage cleanup failed. It'll be retried automatically — please try again.",
        );
      } else {
        toast.error(err.message || "Delete failed");
      }
    },
  });
}

export function useSignedUrl() {
  return useMutation<SignedUrlResponse, ApiError, { id: string; mode: SignedUrlMode }>({
    mutationFn: ({ id, mode }) => filesApi.signedUrl(id, mode),
    onError: (err) => toast.error(err.message || "Could not generate link"),
  });
}

export type BulkDeleteResult = {
  succeeded: string[];
  failed: { id: string; name: string; error: string }[];
};

/**
 * Sequentially calls DELETE /api/files/{id} for each selected file.
 *
 * Sequential — not parallel — because the server-side `delete_file` takes a
 * row-level lock and synchronously purges every B2 version before returning.
 * Parallelism would not only bunch up B2 rate-limited purge calls but also
 * make the failure summary racier to reason about. With sequential loops,
 * the failed list is in input order and the user can retry the leftovers.
 *
 * Partial-failure behavior: we never short-circuit. One bad file does not
 * block the others. The caller gets a per-file summary and shows toasts
 * accordingly.
 *
 * Invalidation happens once at the end so the grid doesn't re-render N
 * times mid-batch. Selection clearing is the caller's responsibility.
 */
export function useBulkDelete() {
  const qc = useQueryClient();
  return useMutation<
    BulkDeleteResult,
    ApiError,
    { files: { id: string; name: string }[] }
  >({
    mutationFn: async ({ files }) => {
      const result: BulkDeleteResult = { succeeded: [], failed: [] };
      for (const f of files) {
        try {
          await filesApi.remove(f.id);
          result.succeeded.push(f.id);
        } catch (err) {
          let message = "Delete failed";
          if (err instanceof ApiError) {
            if (err.code === "FILE_BUSY") {
              message = "Still uploading — try again shortly.";
            } else if (err.code === "STORAGE_PURGE_FAILED") {
              message = "Storage cleanup failed; will retry.";
            } else {
              message = err.message || "Delete failed";
            }
          } else if (err instanceof Error) {
            message = err.message;
          }
          result.failed.push({ id: f.id, name: f.name, error: message });
        }
      }
      return result;
    },
    onSettled: () => {
      // Always refresh — even on partial failure at least some rows changed.
      qc.invalidateQueries({ queryKey: filesKeys.all });
      qc.invalidateQueries({ queryKey: filesKeys.storage() });
    },
    onSuccess: (result) => {
      const ok = result.succeeded.length;
      const bad = result.failed.length;
      if (ok > 0 && bad === 0) {
        toast.success(ok === 1 ? "File deleted" : `Deleted ${ok} files`);
      } else if (ok > 0 && bad > 0) {
        toast.warning(`Deleted ${ok}, ${bad} failed`);
      } else if (bad > 0) {
        // All failed — surface the first error so the reason is visible.
        toast.error(
          bad === 1 ? result.failed[0]!.error : `All ${bad} deletes failed`,
        );
      }
    },
  });
}

// ── Folders ──────────────────────────────────────────────────────

export function useFolders(
  parentId: string | null = null,
  options?: Omit<UseQueryOptions<FolderListResponse, ApiError>, "queryKey" | "queryFn">,
) {
  return useQuery<FolderListResponse, ApiError>({
    queryKey: foldersKeys.list(parentId),
    queryFn: () => foldersApi.list(parentId),
    ...options,
  });
}

export function useCreateFolder() {
  const qc = useQueryClient();
  return useMutation<
    FolderItem,
    ApiError,
    { name: string; parent_id?: string | null }
  >({
    mutationFn: (payload) => foldersApi.create(payload),
    onSuccess: (folder) => {
      toast.success(`Created folder "${folder.name}"`);
      // Invalidate the whole folder tree — counts on ancestors may have
      // shifted. File list is unaffected, so don't evict those caches.
      qc.invalidateQueries({ queryKey: foldersKeys.all });
    },
    onError: (err) => {
      if (err.code === "FOLDER_CONFLICT") {
        toast.error("A folder with this name already exists here.");
      } else if (err.code === "FOLDER_NAME_INVALID") {
        toast.error(err.message);
      } else {
        toast.error(err.message || "Could not create folder");
      }
    },
  });
}

export function useDeleteFolder() {
  const qc = useQueryClient();
  return useMutation<
    FolderDeleteResult,
    ApiError,
    { id: string; name: string }
  >({
    mutationFn: ({ id }) => foldersApi.remove(id),
    onSuccess: (result, vars) => {
      const files = result.files_deleted;
      const folders = result.folders_deleted;
      toast.success(
        `Deleted "${vars.name}"` +
          (files > 0 ? ` (${files} file${files === 1 ? "" : "s"})` : "") +
          (folders > 1 ? ` and ${folders - 1} subfolder${folders - 1 === 1 ? "" : "s"}` : ""),
      );
      // The delete cascaded — refresh both files and folders.
      qc.invalidateQueries({ queryKey: foldersKeys.all });
      qc.invalidateQueries({ queryKey: filesKeys.all });
      qc.invalidateQueries({ queryKey: filesKeys.storage() });
    },
    onError: (err) => {
      if (err.code === "FOLDER_TOO_LARGE") {
        toast.error(err.message);
      } else if (err.code === "FILE_BUSY") {
        toast.error("A file in this folder is still uploading — try again shortly.");
      } else if (err.code === "STORAGE_PURGE_FAILED") {
        toast.error(
          "Storage cleanup failed partway through — please retry. Already-removed files won't be touched.",
        );
        // Partial progress — still invalidate so UI reflects what *did* go.
        qc.invalidateQueries({ queryKey: foldersKeys.all });
        qc.invalidateQueries({ queryKey: filesKeys.all });
        qc.invalidateQueries({ queryKey: filesKeys.storage() });
      } else {
        toast.error(err.message || "Could not delete folder");
      }
    },
  });
}

/**
 * Fetch a one-shot signed URL for downloading a folder as ZIP. Returns
 * the URL synchronously — the caller triggers navigation (usually via
 * a transient <a download> click) to start the stream.
 */
export function useFolderDownloadUrl() {
  return useMutation<FolderDownloadUrlResponse, ApiError, { id: string; name: string }>({
    mutationFn: ({ id }) => foldersApi.downloadUrl(id),
    onError: (err) => {
      if (err.code === "FOLDER_TOO_LARGE") {
        toast.error(err.message);
      } else {
        toast.error(err.message || "Could not prepare download");
      }
    },
  });
}

export type { UploadProgress };
