"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Skeleton } from "@/components/ui/skeleton";
import { filesApi } from "../api";
import { useDeleteFile, useFiles } from "../hooks";
import type { FileItem } from "../types";
import { PreviewDialog } from "@/features/preview/PreviewDialog";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";
import { EmptyState } from "./EmptyState";
import { FileCard } from "./FileCard";
import { FileRow } from "./FileRow";
import { SearchBar } from "./SearchBar";
import { UploadButton } from "./UploadButton";
import { ViewToggle, type ViewMode } from "./ViewToggle";

function matchesQuery(file: FileItem, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return (
    file.name.toLowerCase().includes(needle) ||
    file.extension.toLowerCase().includes(needle)
  );
}

export function FileList() {
  const [view, setView] = useState<ViewMode>("list");
  const [query, setQuery] = useState("");
  const [toDelete, setToDelete] = useState<FileItem | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);

  const { data, isLoading, isError, error, refetch, isRefetching } = useFiles(
    { page: 1, page_size: 100 },
    {
      // Poll while any file is in a transient state so the UI flips to ready automatically.
      refetchInterval: (q) => {
        const items = q.state.data?.items ?? [];
        const transient = items.some((f) => f.status === "uploading" || f.status === "deleting");
        return transient ? 3000 : false;
      },
    },
  );
  const deleteMutation = useDeleteFile();

  const filtered = useMemo(() => {
    const items = data?.items ?? [];
    if (!query) return items;
    return items.filter((f) => matchesQuery(f, query));
  }, [data, query]);

  const handleDownload = async (file: FileItem) => {
    try {
      const res = await filesApi.signedUrl(file.id, "download");
      // Navigate directly — backend sets Content-Disposition: attachment.
      window.location.href = res.url;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not download";
      toast.error(msg);
    }
  };

  const handleConfirmDelete = () => {
    if (!toDelete) return;
    const f = toDelete;
    deleteMutation.mutate(
      { id: f.id, name: f.name },
      {
        onSettled: () => setToDelete(null),
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <SearchBar value={query} onChange={setQuery} />
          <ViewToggle mode={view} onChange={setView} />
        </div>
        <UploadButton />
      </div>

      {isLoading ? (
        <div className="grid gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Could not load files.</p>
          <p className="mt-1 text-red-600">{error?.message ?? "Unknown error"}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-2 text-sm font-medium underline underline-offset-2"
          >
            Retry
          </button>
        </div>
      ) : filtered.length === 0 && query ? (
        <EmptyState
          title="No matches"
          description={`No files match “${query}”.`}
        />
      ) : filtered.length === 0 ? (
        <EmptyState />
      ) : view === "list" ? (
        <div className="grid gap-2">
          {filtered.map((f) => (
            <FileRow
              key={f.id}
              file={f}
              onPreview={setPreview}
              onDownload={handleDownload}
              onDelete={setToDelete}
            />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((f) => (
            <FileCard
              key={f.id}
              file={f}
              onPreview={setPreview}
              onDownload={handleDownload}
              onDelete={setToDelete}
            />
          ))}
        </div>
      )}

      {isRefetching && !isLoading ? (
        <p className="text-right text-xs text-neutral-400">Refreshing…</p>
      ) : null}

      <DeleteConfirmDialog
        file={toDelete}
        open={toDelete !== null}
        onOpenChange={(o) => !o && setToDelete(null)}
        onConfirm={handleConfirmDelete}
        isDeleting={deleteMutation.isPending}
      />
      <PreviewDialog
        file={preview}
        open={preview !== null}
        onOpenChange={(o) => !o && setPreview(null)}
      />
    </div>
  );
}
