"use client";

/**
 * Multi-file & folder uploader.
 *
 * The backend endpoint is per-file (POST /api/files accepts a single
 * UploadedFile), so a "batch upload" here means one HTTP request per file,
 * issued sequentially. Sequential — not parallel — for three reasons:
 *   1. Two files in the same batch that share a name would race through the
 *      upload_file Phase 5 purge; sequential keeps last-write-wins
 *      deterministic (the later file wins, as the picker ordered them).
 *   2. The per-user upload rate limit is easier to reason about when
 *      requests go out one at a time.
 *   3. Per-file progress % stays meaningful — users see one bar moving.
 *
 * Folder uploads: browsers expose a `webkitRelativePath` on File objects
 * picked via a `webkitdirectory`-flagged input. We strip the filename and
 * send the remaining directory chain as `relative_path`; the server calls
 * `ensure_folder_path` to lazily materialize any missing segments under
 * the target parent. Cross-browser note: `webkitdirectory` is non-standard
 * but is implemented in Chromium, Safari, and Firefox — the three browsers
 * this app targets.
 *
 * UI modes, by batch size:
 *   - 1 file  → minimal inline progress bar under the button + toast.
 *               No panel. Matches the pre-batch single-file UX.
 *   - >1 file → panel with per-row status. Auto-dismisses 5s after the
 *               batch finishes, or immediately when the user clicks ✕.
 *
 * Timer discipline (see useEffect below): a single ref holds the pending
 * auto-dismiss. The effect cleanup clears it on every re-run, which covers
 * manual close, a new batch starting mid-countdown, and unmount — all with
 * one code path.
 *
 * Validation is client-side pre-flight for fast feedback (extension + size);
 * the server re-validates everything and remains the source of truth. Quota
 * is server-side only because the reclaim-same-name logic needs a DB
 * snapshot under lock.
 *
 * List + storage-usage invalidation happens once, after the whole batch, so
 * the grid doesn't thrash through N re-renders during a large upload.
 */

import { useEffect, useRef, useState } from "react";
import {
  Upload,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
  FolderUp,
  FileUp,
  ChevronDown,
} from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { ApiError } from "@/lib/api";

import { filesApi } from "../api";
import { filesKeys, foldersKeys } from "../hooks";
import { ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES } from "../types";
import { formatBytes } from "../utils";

const ACCEPT = ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",");
const BATCH_PANEL_DISMISS_MS = 5000;

type ItemStatus = "pending" | "uploading" | "success" | "failed";

type BatchItem = {
  /** Stable local id for React keys; does not round-trip to the server. */
  localId: string;
  file: File;
  /** Directory portion of webkitRelativePath, "" for flat uploads. */
  relativeDir: string;
  /** Display name with any folder prefix ("contracts/2024/a.pdf"). */
  displayPath: string;
  status: ItemStatus;
  /** 0–100, meaningful only while status === "uploading" or "success". */
  progress: number;
  error?: string;
};

function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i >= 0 ? filename.slice(i + 1).toLowerCase() : "";
}

function clientValidate(file: File): string | null {
  const ext = extOf(file.name);
  if (!ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
    return `Unsupported file type: .${ext || "unknown"}`;
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `Too large (max ${formatBytes(MAX_FILE_SIZE_BYTES)})`;
  }
  if (file.size === 0) {
    return "Empty file";
  }
  return null;
}

/** Cheap, collision-resistant local id. Not used on the wire. */
function makeLocalId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function isTerminal(s: ItemStatus): boolean {
  return s === "success" || s === "failed";
}

/** Split webkitRelativePath into (directoryPath, filename). The leading
 *  component is always the folder the user picked, which we keep — it
 *  becomes the top of the uploaded hierarchy. */
function splitRelativePath(file: File): { relativeDir: string; displayPath: string } {
  // File.webkitRelativePath is "" for files picked without webkitdirectory.
  const raw = (file as File & { webkitRelativePath?: string }).webkitRelativePath ?? "";
  if (!raw) {
    return { relativeDir: "", displayPath: file.name };
  }
  const lastSlash = raw.lastIndexOf("/");
  if (lastSlash <= 0) {
    return { relativeDir: "", displayPath: raw };
  }
  return { relativeDir: raw.slice(0, lastSlash), displayPath: raw };
}

export function UploadButton({
  folderId = null,
}: {
  /** Target folder id for uploads. Null/undefined = root. */
  folderId?: string | null;
}) {
  const filesInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const [items, setItems] = useState<BatchItem[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  // One timer id lives at a time. Effect below arms it; effect cleanup clears
  // it. Manual close and "new batch started" both clear items — that
  // re-runs the effect, whose cleanup clears the pending timeout. No extra
  // bookkeeping needed for those cases.
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Single-file flow never shows the panel, so it never needs a timer.
    if (items.length <= 1) return;
    // Don't arm while work is in flight — the spec is explicit about this.
    if (isUploading) return;
    // Defensive: require every row to be in a terminal state before arming.
    // `isUploading` should already guarantee this, but the check makes the
    // invariant local to the effect.
    if (!items.every((it) => isTerminal(it.status))) return;

    dismissTimerRef.current = setTimeout(() => {
      setItems([]);
      dismissTimerRef.current = null;
    }, BATCH_PANEL_DISMISS_MS);

    return () => {
      if (dismissTimerRef.current !== null) {
        clearTimeout(dismissTimerRef.current);
        dismissTimerRef.current = null;
      }
    };
  }, [items, isUploading]);

  const handlePickFiles = () => filesInputRef.current?.click();
  const handlePickFolder = () => folderInputRef.current?.click();

  const updateItem = (localId: string, patch: Partial<BatchItem>) => {
    setItems((prev) =>
      prev.map((it) => (it.localId === localId ? { ...it, ...patch } : it)),
    );
  };

  const runBatch = async (picked: File[]) => {
    // Build the batch with client-side validation applied up-front. Invalid
    // files enter the list as "failed" so the user sees the error without
    // wondering why we silently dropped their selection.
    const batch: BatchItem[] = picked.map((file) => {
      const err = clientValidate(file);
      const { relativeDir, displayPath } = splitRelativePath(file);
      return {
        localId: makeLocalId(),
        file,
        relativeDir,
        displayPath,
        status: err ? "failed" : "pending",
        progress: 0,
        error: err ?? undefined,
      };
    });

    // Replace any previous batch — the user just started a new selection.
    // The effect's cleanup will clear any pending auto-dismiss for us.
    setItems(batch);
    setIsUploading(true);

    let successCount = 0;
    let failCount = batch.filter((it) => it.status === "failed").length;
    let lastSuccessName: string | null = null;
    let lastFailError: string | null =
      batch.find((b) => b.status === "failed")?.error ?? null;

    try {
      // Sequential: await each upload before starting the next.
      for (const item of batch) {
        if (item.status === "failed") continue;

        updateItem(item.localId, { status: "uploading", progress: 0 });
        try {
          await filesApi.upload(item.file, {
            folderId,
            relativePath: item.relativeDir || undefined,
            onProgress: (p) =>
              updateItem(item.localId, { progress: p.percent }),
          });
          updateItem(item.localId, { status: "success", progress: 100 });
          successCount += 1;
          lastSuccessName = item.displayPath;
        } catch (err) {
          const message =
            err instanceof ApiError
              ? err.message || "Upload failed"
              : err instanceof Error
                ? err.message
                : "Upload failed";
          updateItem(item.localId, { status: "failed", error: message });
          failCount += 1;
          lastFailError = message;
        }
      }
    } finally {
      setIsUploading(false);
      // One invalidation at the end of the batch — not per file — so the
      // grid doesn't re-render N times mid-upload. Folder uploads may
      // have created new folders via ensure_folder_path, so invalidate
      // the folder tree as well.
      if (successCount > 0) {
        qc.invalidateQueries({ queryKey: filesKeys.all });
        qc.invalidateQueries({ queryKey: foldersKeys.all });
        qc.invalidateQueries({ queryKey: filesKeys.storage() });
      }
      if (filesInputRef.current) filesInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";

      // Single-file flow: no panel, so clear the inline row immediately.
      // Toast below carries the result. Multi-file batches stay on screen
      // until the useEffect auto-dismiss fires (5s) or the user clicks ✕.
      if (batch.length === 1) {
        setItems([]);
      }
    }

    // Toast policy:
    //   single-file → one granular toast (existing behavior).
    //   multi-file  → one summary toast; per-row errors live in the panel.
    if (batch.length === 1) {
      if (successCount === 1) {
        toast.success(`Uploaded ${lastSuccessName ?? "file"}`);
      } else {
        toast.error(lastFailError ?? "Upload failed");
      }
    } else {
      if (failCount === 0 && successCount > 0) {
        toast.success(`Uploaded ${successCount} files`);
      } else if (successCount > 0 && failCount > 0) {
        toast.warning(`Uploaded ${successCount}, ${failCount} failed`);
      } else if (failCount > 0 && successCount === 0) {
        toast.error(`All ${failCount} uploads failed`);
      }
    }
  };

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length === 0) return;
    void runBatch(picked);
  };

  // Manual close: blowing away `items` re-runs the effect, whose cleanup
  // clears the pending timer. No separate timer-clear call needed here.
  const clearItems = () => setItems([]);

  const isBatch = items.length > 1;
  const isSingleInFlight = items.length === 1 && isUploading;
  const allDone =
    isBatch && !isUploading && items.every((it) => isTerminal(it.status));

  return (
    <div className="flex w-full max-w-md flex-col items-end gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button disabled={isUploading}>
            <Upload className="mr-2 h-4 w-4" />
            {isUploading ? "Uploading…" : "Upload"}
            <ChevronDown className="ml-2 h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={handlePickFiles}>
            <FileUp className="h-4 w-4" />
            Upload files
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={handlePickFolder}>
            <FolderUp className="h-4 w-4" />
            Upload folder
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <input
        ref={filesInputRef}
        type="file"
        accept={ACCEPT}
        multiple
        onChange={onChange}
        className="hidden"
        aria-hidden
      />
      {/*
        `webkitdirectory` is not in the standard React TS defs; cast on
        the spread to keep TS happy. The attribute is supported by all
        Chromium browsers, Safari, and Firefox. `directory` is the legacy
        attribute that Firefox historically recognized — harmless on others.
      */}
      <input
        ref={folderInputRef}
        type="file"
        multiple
        onChange={onChange}
        className="hidden"
        aria-hidden
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
      />

      {isSingleInFlight ? <SingleInlineProgress item={items[0]!} /> : null}

      {isBatch ? (
        <div className="w-full rounded-md border border-neutral-200 bg-white p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-neutral-700">
              {isUploading ? "Uploading…" : "Batch complete"}
            </span>
            {allDone ? (
              <button
                type="button"
                onClick={clearItems}
                className="text-xs text-neutral-500 hover:text-neutral-800"
                aria-label="Dismiss"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
          <ul className="space-y-2">
            {items.map((it) => (
              <BatchItemRow key={it.localId} item={it} />
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function SingleInlineProgress({ item }: { item: BatchItem }) {
  return (
    <div className="w-56 space-y-1">
      <div className="flex justify-between text-xs text-neutral-600">
        <span className="truncate" title={item.displayPath}>
          {item.displayPath}
        </span>
        <span className="tabular-nums">{item.progress}%</span>
      </div>
      <Progress value={item.progress} />
    </div>
  );
}

function BatchItemRow({ item }: { item: BatchItem }) {
  return (
    <li className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-xs">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <StatusIcon status={item.status} />
          <span
            className="truncate text-neutral-800"
            title={item.displayPath}
          >
            {item.displayPath}
          </span>
          <span className="shrink-0 text-neutral-500">
            {formatBytes(item.file.size)}
          </span>
        </div>
        <StatusLabel item={item} />
      </div>
      {item.status === "uploading" ? (
        <Progress value={item.progress} />
      ) : null}
      {item.status === "failed" && item.error ? (
        <p className="text-xs text-red-600" role="alert">
          {item.error}
        </p>
      ) : null}
    </li>
  );
}

function StatusIcon({ status }: { status: ItemStatus }) {
  switch (status) {
    case "uploading":
      return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" aria-hidden />;
    case "success":
      return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden />;
    case "failed":
      return <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-600" aria-hidden />;
    case "pending":
    default:
      return <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-neutral-300" aria-hidden />;
  }
}

function StatusLabel({ item }: { item: BatchItem }) {
  switch (item.status) {
    case "pending":
      return <span className="shrink-0 text-neutral-500">Pending</span>;
    case "uploading":
      return <span className="shrink-0 tabular-nums text-neutral-600">{item.progress}%</span>;
    case "success":
      return <span className="shrink-0 text-emerald-700">Done</span>;
    case "failed":
      return <span className="shrink-0 text-red-600">Failed</span>;
  }
}
