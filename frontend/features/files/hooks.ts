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
import { filesApi, type UploadOptions, type UploadProgress, type ListFilesParams } from "./api";
import type {
  FileItem,
  FileListResponse,
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
};

export function useUploadFile() {
  const qc = useQueryClient();
  return useMutation<FileItem, ApiError, UploadArgs>({
    mutationFn: ({ file, onProgress, signal }) =>
      filesApi.upload(file, { onProgress, signal }),
    onSuccess: (item) => {
      toast.success(`Uploaded ${item.name}`);
      qc.invalidateQueries({ queryKey: filesKeys.all });
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

export type { UploadProgress };
