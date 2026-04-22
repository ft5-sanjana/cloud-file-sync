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
    onError: (err) => toast.error(err.message || "Delete failed"),
  });
}

export function useSignedUrl() {
  return useMutation<SignedUrlResponse, ApiError, { id: string; mode: SignedUrlMode }>({
    mutationFn: ({ id, mode }) => filesApi.signedUrl(id, mode),
    onError: (err) => toast.error(err.message || "Could not generate link"),
  });
}

export type { UploadProgress };
