"use client";

import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Checkbox, type CheckboxState } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";

import { PreviewDialog } from "@/features/preview/PreviewDialog";

import { filesApi } from "../api";
import { useBulkDelete, useDeleteFile, useFiles } from "../hooks";
import type { FileItem } from "../types";
import { BulkActionBar } from "./BulkActionBar";
import { BulkDeleteDialog } from "./BulkDeleteDialog";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";
import { EmptyState } from "./EmptyState";
import { FileCard } from "./FileCard";
import { FileRow } from "./FileRow";
import { SearchBar } from "./SearchBar";
import { UploadButton } from "./UploadButton";
import { ViewToggle, type ViewMode } from "./ViewToggle";

/** Spacing between sequential bulk downloads — the browser gives each a
 *  distinct user-gesture-ish window. Too tight and Chrome blocks, too
 *  loose and the user waits. 300ms is the sweet spot in practice. */
const BULK_DOWNLOAD_STAGGER_MS = 300;

function matchesQuery(file: FileItem, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return (
    file.name.toLowerCase().includes(needle) ||
    file.extension.toLowerCase().includes(needle)
  );
}

/** Trigger a same-origin download by programmatically clicking an <a>. The
 *  browser honours the signed URL's Content-Disposition: attachment so no
 *  navigation or tab-open happens. */
function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  // `download` is only honoured same-origin, but we still set it as a hint —
  // the Content-Disposition header on the signed URL is what actually forces
  // the save dialog for cross-origin (B2) responses.
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function FileList() {
  const [view, setView] = useState<ViewMode>("list");
  const [query, setQuery] = useState("");
  const [toDelete, setToDelete] = useState<FileItem | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);

  // Selection = Set<string> of file IDs. Kept immutable-ish: every mutation
  // allocates a new Set so React picks up the change. Persists across search
  // filter changes intentionally (Gmail/Drive pattern — filtering doesn't
  // unselect things you can no longer see).
  const [selection, setSelection] = useState<Set<string>>(new Set());

  // Bulk-download busy state is local — downloads aren't React-Query mutations
  // (no cache to invalidate, no server state to sync).
  const [isBulkDownloading, setIsBulkDownloading] = useState(false);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  const { data, isLoading, isError, error, refetch, isRefetching } = useFiles(
    { page: 1, page_size: 100 },
    {
      refetchInterval: (q) => {
        const items = q.state.data?.items ?? [];
        const transient = items.some(
          (f) => f.status === "uploading" || f.status === "deleting",
        );
        return transient ? 3000 : false;
      },
    },
  );
  const deleteMutation = useDeleteFile();
  const bulkDelete = useBulkDelete();

  const filtered = useMemo(() => {
    const items = data?.items ?? [];
    if (!query) return items;
    return items.filter((f) => matchesQuery(f, query));
  }, [data, query]);

  // Derived selection counts.
  // `visibleIds` drives the Select-All tri-state. The actual bulk action
  // operates on the full `selection` (which may include rows not currently
  // visible under the search filter — intentional).
  const visibleIds = useMemo(() => filtered.map((f) => f.id), [filtered]);
  const selectedVisibleCount = useMemo(() => {
    let n = 0;
    for (const id of visibleIds) if (selection.has(id)) n += 1;
    return n;
  }, [visibleIds, selection]);

  const selectAllState: CheckboxState =
    visibleIds.length === 0
      ? "unchecked"
      : selectedVisibleCount === 0
        ? "unchecked"
        : selectedVisibleCount === visibleIds.length
          ? "checked"
          : "indeterminate";

  // ── Selection mutators ────────────────────────────────────────────
  const toggleOne = useCallback((id: string) => {
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAllVisible = useCallback(() => {
    setSelection((prev) => {
      const next = new Set(prev);
      // If every visible row is already selected → deselect those visible
      // rows only. Leaves any non-visible selections alone.
      const allVisibleSelected =
        visibleIds.length > 0 && visibleIds.every((id) => next.has(id));
      if (allVisibleSelected) {
        for (const id of visibleIds) next.delete(id);
      } else {
        for (const id of visibleIds) next.add(id);
      }
      return next;
    });
  }, [visibleIds]);

  const clearSelection = useCallback(() => {
    setSelection(new Set());
  }, []);

  // ── Per-file handlers ─────────────────────────────────────────────
  const handleDownload = async (file: FileItem) => {
    try {
      const res = await filesApi.signedUrl(file.id, "download");
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
        onSettled: () => {
          setToDelete(null);
          // If the single-file delete target was also in the multi-select,
          // drop it from selection so the UI stays consistent.
          setSelection((prev) => {
            if (!prev.has(f.id)) return prev;
            const next = new Set(prev);
            next.delete(f.id);
            return next;
          });
        },
      },
    );
  };

  // ── Bulk handlers ─────────────────────────────────────────────────
  const handleBulkDownload = async () => {
    if (selection.size === 0 || isBulkDownloading) return;

    // Resolve IDs against the current server-known files. We do NOT trust
    // selection to match stale visible rows — always cross-check. Files
    // that vanished between selection and action are reported as errors.
    const byId = new Map((data?.items ?? []).map((f) => [f.id, f]));
    const targets: FileItem[] = [];
    const stale: string[] = [];
    for (const id of selection) {
      const hit = byId.get(id);
      if (hit && hit.status === "ready") targets.push(hit);
      else stale.push(id);
    }

    if (targets.length === 0) {
      toast.error("Selected files are no longer available.");
      return;
    }

    setIsBulkDownloading(true);
    let succeeded = 0;
    const failed: { name: string; error: string }[] = [];
    try {
      for (let i = 0; i < targets.length; i += 1) {
        const f = targets[i]!;
        try {
          const res = await filesApi.signedUrl(f.id, "download");
          triggerDownload(res.url, f.name);
          succeeded += 1;
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Could not download";
          failed.push({ name: f.name, error: msg });
        }
        // Stagger triggers so the browser doesn't coalesce/block them. Skip
        // the delay after the final file to avoid needless tail latency.
        if (i < targets.length - 1) await sleep(BULK_DOWNLOAD_STAGGER_MS);
      }
    } finally {
      setIsBulkDownloading(false);
    }

    const total = succeeded + failed.length + stale.length;
    if (failed.length === 0 && stale.length === 0) {
      toast.success(
        succeeded === 1
          ? "Downloading 1 file"
          : `Downloading ${succeeded} files`,
      );
    } else if (succeeded > 0) {
      toast.warning(
        `Started ${succeeded} of ${total} downloads${
          failed.length ? `; ${failed.length} failed` : ""
        }${stale.length ? `; ${stale.length} unavailable` : ""}`,
      );
    } else {
      toast.error(
        failed.length === 1
          ? failed[0]!.error
          : `Could not start ${total} download${total === 1 ? "" : "s"}`,
      );
    }
    // Selection intentionally preserved after bulk download — user may want
    // to run another action (e.g. delete) on the same set.
  };

  const handleConfirmBulkDelete = () => {
    if (selection.size === 0) return;
    const byId = new Map((data?.items ?? []).map((f) => [f.id, f]));
    const files: { id: string; name: string }[] = [];
    for (const id of selection) {
      const hit = byId.get(id);
      files.push({ id, name: hit?.name ?? "file" });
    }

    bulkDelete.mutate(
      { files },
      {
        onSettled: () => {
          setBulkDeleteOpen(false);
          clearSelection();
        },
      },
    );
  };

  const hasFiles = (data?.items ?? []).length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <SearchBar value={query} onChange={setQuery} />
          <ViewToggle mode={view} onChange={setView} />
        </div>
        <UploadButton />
      </div>

      <BulkActionBar
        selectedCount={selection.size}
        onDownload={handleBulkDownload}
        onDelete={() => setBulkDeleteOpen(true)}
        onClear={clearSelection}
        isDownloading={isBulkDownloading}
        isDeleting={bulkDelete.isPending}
      />

      {/* Select-all header — only meaningful when we have visible files and
          we're not in a loading / error / empty state. */}
      {hasFiles && filtered.length > 0 ? (
        <div className="flex items-center gap-3 px-1 text-xs text-neutral-600">
          <Checkbox
            state={selectAllState}
            onToggle={toggleAllVisible}
            ariaLabel={
              selectAllState === "checked"
                ? "Deselect all visible files"
                : "Select all visible files"
            }
          />
          <span>
            {selectAllState === "checked"
              ? `All ${filtered.length} visible selected`
              : selectAllState === "indeterminate"
                ? `${selectedVisibleCount} of ${filtered.length} visible selected`
                : `Select all ${filtered.length} visible`}
          </span>
        </div>
      ) : null}

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
              selected={selection.has(f.id)}
              onToggleSelect={toggleOne}
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
              selected={selection.has(f.id)}
              onToggleSelect={toggleOne}
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
      <BulkDeleteDialog
        count={selection.size}
        open={bulkDeleteOpen}
        onOpenChange={(o) => !bulkDelete.isPending && setBulkDeleteOpen(o)}
        onConfirm={handleConfirmBulkDelete}
        isDeleting={bulkDelete.isPending}
      />
      <PreviewDialog
        file={preview}
        open={preview !== null}
        onOpenChange={(o) => !o && setPreview(null)}
      />
    </div>
  );
}
