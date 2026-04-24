"use client";

/**
 * Grid-view card for a folder. Same split as FolderRow: the card body
 * is a single clickable target that opens the folder, with the action
 * dropdown layered on top and isolated from the click.
 */

import { Folder as FolderIcon } from "lucide-react";

import type { FolderItem } from "../types";
import { formatDate } from "../utils";
import { FolderActions } from "./FolderActions";

export function FolderCard({
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
    <div className="group relative rounded-lg border border-neutral-200 bg-white transition-colors hover:bg-neutral-50">
      <div className="absolute right-2 top-2 z-10" onClick={(e) => e.stopPropagation()}>
        <FolderActions
          folder={folder}
          onDownload={onDownload}
          onDelete={onDelete}
        />
      </div>
      <button
        type="button"
        onClick={() => onOpen(folder)}
        className="flex w-full flex-col p-4 text-left"
        aria-label={`Open folder ${folder.name}`}
      >
        <div className="flex items-center justify-center rounded-md bg-neutral-100 py-8">
          <FolderIcon className="h-12 w-12 text-amber-500" aria-hidden />
        </div>
        <div className="mt-3 min-w-0">
          <p
            className="truncate text-sm font-medium text-neutral-900"
            title={folder.name}
          >
            {folder.name}
          </p>
          <div className="mt-1 flex items-center justify-between text-xs text-neutral-500">
            <span>
              {entryCount === 0
                ? "Empty"
                : `${folder.file_count} file${folder.file_count === 1 ? "" : "s"}` +
                  (folder.subfolder_count > 0
                    ? ` · ${folder.subfolder_count} folder${folder.subfolder_count === 1 ? "" : "s"}`
                    : "")}
            </span>
            <span>{formatDate(folder.updated_at)}</span>
          </div>
        </div>
      </button>
    </div>
  );
}
