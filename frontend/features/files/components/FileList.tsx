"use client";

/**
 * Top-level files + folders view.
 *
 * Navigation state lives in this component (not the URL) to keep the
 * feature self-contained: entering a folder pushes it onto the trail;
 * clicking a crumb truncates. On refresh the view resets to root. URL
 * deep-links would require a server-side ancestor endpoint — deferred.
 *
 * The search flow is a deliberate fork:
 *   - When the user types into the search box, the file list switches to
 *     a server-wide query (`q` param) that ignores folder scope. Folders
 *     disappear from the view during search so the results stay one flat
 *     list the user can scan.
 *   - With no query, we request folders for the current parent AND files
 *     whose folder_id matches, stitched together visually.
 *
 * Selection operates on files only. Folders have their own per-item
 * download/delete dropdown; there's no "select 3 folders, download them
 * all" flow in the MVP.
 */

import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Checkbox, type CheckboxState } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ArrowLeft, FolderPlus } from "lucide-react";

import { PreviewDialog } from "@/features/preview/PreviewDialog";
import { ApiError } from "@/lib/api";

import { filesApi } from "../api";
import {
  useBulkDelete,
  useCreateFolder,
  useDeleteFile,
  useDeleteFolder,
  useFiles,
  useFolderDownloadUrl,
  useFolders,
} from "../hooks";
import type { FileItem, FolderItem } from "../types";
import { BulkActionBar } from "./BulkActionBar";
import { BulkDeleteDialog } from "./BulkDeleteDialog";
import { Breadcrumb, type BreadcrumbItem } from "./Breadcrumb";
import { CreateFolderDialog } from "./CreateFolderDialog";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";
import { DeleteFolderDialog } from "./DeleteFolderDialog";
import { EmptyState } from "./EmptyState";
import { FileCard } from "./FileCard";
import { FileRow } from "./FileRow";
import { FolderCard } from "./FolderCard";
import { FolderRow } from "./FolderRow";
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
  const [folderToDelete, setFolderToDelete] = useState<FolderItem | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [createFolderOpen, setCreateFolderOpen] = useState(false);

  // Navigation trail — shallowest-to-deepest ancestors of the current
  // folder (inclusive). Empty trail = at root. Current folder id is
  // the last entry's id, or null at root.
  const [trail, setTrail] = useState<BreadcrumbItem[]>([]);
  const currentFolderId = trail.length > 0 ? trail[trail.length - 1]!.id : null;

  // Selection = Set<string> of file IDs. Kept immutable-ish: every mutation
  // allocates a new Set so React picks up the change. Cleared when the
  // user changes folders — selection is scoped to the current view.
  const [selection, setSelection] = useState<Set<string>>(new Set());

  // Bulk-download busy state is local — downloads aren't React-Query mutations
  // (no cache to invalidate, no server state to sync).
  const [isBulkDownloading, setIsBulkDownloading] = useState(false);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);

  const isSearching = query.trim().length > 0;

  // When searching we ignore folder scope (`q` spans the whole tree);
  // otherwise we scope files to the current folder.
  const {
    data: fileData,
    isLoading: filesLoading,
    isError: filesError,
    error: filesErrorObj,
    refetch: refetchFiles,
    isRefetching: filesRefetching,
  } = useFiles(
    {
      page: 1,
      page_size: 100,
      q: isSearching ? query : undefined,
      folder_id: isSearching ? undefined : currentFolderId,
    },
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

  // Folders list: always scoped to the current parent. We hide the
  // folder grid entirely during search so results stay a flat list.
  const { data: folderData, isLoading: foldersLoading } = useFolders(
    currentFolderId,
    { enabled: !isSearching },
  );

  const deleteMutation = useDeleteFile();
  const deleteFolderMutation = useDeleteFolder();
  const createFolderMutation = useCreateFolder();
  const folderDownloadMutation = useFolderDownloadUrl();
  const bulkDelete = useBulkDelete();

  // Files visible in the current view. When searching we already filter
  // server-side, but a cheap client-side pass keeps things snappy as
  // the user types between refetches.
  const filtered = useMemo(() => {
    const items = fileData?.items ?? [];
    if (!query) return items;
    return items.filter((f) => matchesQuery(f, query));
  }, [fileData, query]);

  const folders = folderData?.items ?? [];

  // ── Navigation ────────────────────────────────────────────────────
  const navigateTo = useCallback((folderId: string | null) => {
    if (folderId === null) {
      setTrail([]);
    } else {
      setTrail((prev) => {
        const idx = prev.findIndex((c) => c.id === folderId);
        return idx >= 0 ? prev.slice(0, idx + 1) : prev;
      });
    }
    // Fresh view means fresh selection — keeping cross-folder selections
    // would make the action-bar counts misleading.
    setSelection(new Set());
    setQuery("");
  }, []);

  const openFolder = useCallback((folder: FolderItem) => {
    setTrail((prev) => [...prev, { id: folder.id, name: folder.name }]);
    setSelection(new Set());
  }, []);

  // Back to the immediate parent of the current folder. At depth 1 the
  // parent is root, so we pass null to navigateTo. Routed through the
  // same helper as breadcrumb clicks so selection + search clear
  // consistently and the file/folder queries refetch via their
  // derived `currentFolderId` key.
  const goBack = useCallback(() => {
    if (trail.length === 0) return;
    const parent = trail.length > 1 ? trail[trail.length - 2]! : null;
    navigateTo(parent ? parent.id : null);
  }, [trail, navigateTo]);

  // ── Derived selection state ───────────────────────────────────────
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

  // ── Folder handlers ───────────────────────────────────────────────
  const handleConfirmCreateFolder = (name: string) => {
    createFolderMutation.mutate(
      { name, parent_id: currentFolderId },
      {
        onSuccess: () => setCreateFolderOpen(false),
        // onError: hook already shows the right toast; keep dialog open
        // so the user can tweak the name without retyping from scratch.
      },
    );
  };

  const handleFolderDownload = (folder: FolderItem) => {
    folderDownloadMutation.mutate(
      { id: folder.id, name: folder.name },
      {
        onSuccess: (res) => {
          triggerDownload(res.url, res.filename);
        },
      },
    );
  };

  const handleConfirmFolderDelete = () => {
    if (!folderToDelete) return;
    const f = folderToDelete;
    deleteFolderMutation.mutate(
      { id: f.id, name: f.name },
      {
        onSettled: (_data, err) => {
          // Keep the dialog open only on a "still uploading" transient;
          // every other outcome (success or permanent failure) closes.
          const transient =
            err instanceof ApiError && err.code === "FILE_BUSY";
          if (!transient) setFolderToDelete(null);
        },
      },
    );
  };

  // ── Bulk handlers ─────────────────────────────────────────────────
  const handleBulkDownload = async () => {
    if (selection.size === 0 || isBulkDownloading) return;

    const byId = new Map((fileData?.items ?? []).map((f) => [f.id, f]));
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
  };

  const handleConfirmBulkDelete = () => {
    if (selection.size === 0) return;
    const byId = new Map((fileData?.items ?? []).map((f) => [f.id, f]));
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

  const hasFiles = filtered.length > 0;
  const hasFolders = folders.length > 0;
  const isLoading = filesLoading || (!isSearching && foldersLoading);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <SearchBar value={query} onChange={setQuery} />
          <ViewToggle mode={view} onChange={setView} />
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setCreateFolderOpen(true)}
            disabled={isSearching}
            title={isSearching ? "Clear the search to create folders" : undefined}
          >
            <FolderPlus className="mr-2 h-4 w-4" />
            New folder
          </Button>
          <UploadButton folderId={currentFolderId} />
        </div>
      </div>

      {/* Back + breadcrumb row. Back is only rendered inside a folder
          — at root there's no parent to return to, so a disabled button
          would just be visual noise. */}
      <div className="flex items-center gap-2">
        {trail.length > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={goBack}
            aria-label="Back to parent folder"
            title="Back to parent folder"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
        ) : null}
        <Breadcrumb trail={trail} onNavigate={navigateTo} />
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
      {hasFiles ? (
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
      ) : filesError ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Could not load files.</p>
          <p className="mt-1 text-red-600">
            {filesErrorObj?.message ?? "Unknown error"}
          </p>
          <button
            type="button"
            onClick={() => refetchFiles()}
            className="mt-2 text-sm font-medium underline underline-offset-2"
          >
            Retry
          </button>
        </div>
      ) : !hasFiles && !hasFolders && query ? (
        <EmptyState
          title="No matches"
          description={`Nothing matches “${query}”.`}
        />
      ) : !hasFiles && !hasFolders ? (
        <EmptyState
          title={currentFolderId ? "Folder is empty" : "No files yet"}
          description={
            currentFolderId
              ? "Upload files or create a subfolder to get started."
              : "Upload your first file or create a folder to get started."
          }
        />
      ) : view === "list" ? (
        <div className="grid gap-2">
          {!isSearching &&
            folders.map((f) => (
              <FolderRow
                key={f.id}
                folder={f}
                onOpen={openFolder}
                onDownload={handleFolderDownload}
                onDelete={setFolderToDelete}
              />
            ))}
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
          {!isSearching &&
            folders.map((f) => (
              <FolderCard
                key={f.id}
                folder={f}
                onOpen={openFolder}
                onDownload={handleFolderDownload}
                onDelete={setFolderToDelete}
              />
            ))}
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

      {filesRefetching && !filesLoading ? (
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
      <DeleteFolderDialog
        folder={folderToDelete}
        open={folderToDelete !== null}
        onOpenChange={(o) => {
          if (!o && !deleteFolderMutation.isPending) setFolderToDelete(null);
        }}
        onConfirm={handleConfirmFolderDelete}
        isDeleting={deleteFolderMutation.isPending}
      />
      <CreateFolderDialog
        open={createFolderOpen}
        onOpenChange={(o) => {
          if (!createFolderMutation.isPending) setCreateFolderOpen(o);
        }}
        onConfirm={handleConfirmCreateFolder}
        isPending={createFolderMutation.isPending}
        parentName={
          trail.length > 0 ? trail[trail.length - 1]!.name : null
        }
      />
      <PreviewDialog
        file={preview}
        open={preview !== null}
        onOpenChange={(o) => !o && setPreview(null)}
      />
    </div>
  );
}
