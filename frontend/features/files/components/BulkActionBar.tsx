"use client";

/**
 * Appears above the file list whenever selection.size > 0. Hosts the "N
 * selected" count, Download / Delete buttons, and a Clear-selection button.
 *
 * Busy flag disables the action buttons during in-flight bulk ops so the
 * user can't double-fire a delete. Clear stays active even when busy — if
 * the bulk delete is hung waiting on a slow B2 purge, the user can at least
 * dismiss the selection UI while we keep processing.
 */

import { Download, Loader2, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";

export function BulkActionBar({
  selectedCount,
  onDownload,
  onDelete,
  onClear,
  isDownloading,
  isDeleting,
}: {
  selectedCount: number;
  onDownload: () => void;
  onDelete: () => void;
  onClear: () => void;
  isDownloading?: boolean;
  isDeleting?: boolean;
}) {
  if (selectedCount === 0) return null;

  const busy = Boolean(isDownloading || isDeleting);

  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2"
      role="region"
      aria-label="Bulk file actions"
    >
      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium text-neutral-900">
          {selectedCount} {selectedCount === 1 ? "file" : "files"} selected
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onDownload}
          disabled={busy}
        >
          {isDownloading ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Download className="mr-2 h-4 w-4" aria-hidden />
          )}
          {isDownloading ? "Downloading…" : "Download"}
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={onDelete}
          disabled={busy}
        >
          {isDeleting ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Trash2 className="mr-2 h-4 w-4" aria-hidden />
          )}
          {isDeleting ? "Deleting…" : "Delete"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClear}
          aria-label="Clear selection"
        >
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}
