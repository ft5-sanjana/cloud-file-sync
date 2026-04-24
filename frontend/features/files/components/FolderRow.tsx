"use client";

/**
 * List-view row for a folder. Clicking the main area navigates into the
 * folder; the actions dropdown (download / delete) is isolated with
 * stopPropagation so a menu click doesn't also trigger navigation.
 */

import { Folder as FolderIcon } from "lucide-react";

import type { FolderItem } from "../types";
import { formatDate } from "../utils";
import { FolderActions } from "./FolderActions";

export function FolderRow({
  folder,
  onOpen,
  onDownload,
  onDelete,
}: {
  folder: FolderItem;
  onOpen: (folder: FolderItem) => void;
  onDownload: (folder: FolderItem) => void;
  onDelete: (folder: FolderItem) => void;
}) {
  const entryCount = folder.file_count + folder.subfolder_count;
  return (
    <div className="flex items-center gap-3 rounded-md border border-neutral-200 bg-white px-3 py-2 transition-colors hover:bg-neutral-50">
      <button
        type="button"
        onClick={() => onOpen(folder)}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
        aria-label={`Open folder ${folder.name}`}
      >
        <FolderIcon className="h-6 w-6 shrink-0 text-amber-500" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-neutral-900">
            {folder.name}
          </p>
          <p className="mt-0.5 truncate text-xs text-neutral-500">
            {entryCount === 0
              ? "Empty"
              : `${folder.file_count} file${folder.file_count === 1 ? "" : "s"}` +
                (folder.subfolder_count > 0
                  ? ` · ${folder.subfolder_count} folder${folder.subfolder_count === 1 ? "" : "s"}`
                  : "")}
            {" · "}
            {formatDate(folder.updated_at)}
          </p>
        </div>
      </button>
      <div onClick={(e) => e.stopPropagation()}>
        <FolderActions
          folder={folder}
          onDownload={onDownload}
          onDelete={onDelete}
        />
      </div>
    </div>
  );
}
