"use client";

import type { FileItem } from "../types";
import { formatBytes, formatDate } from "../utils";
import { FileActions } from "./FileActions";
import { FileIcon } from "./FileIcon";
import { StatusBadge } from "./StatusBadge";

export function FileCard({
  file,
  onPreview,
  onDownload,
  onDelete,
}: {
  file: FileItem;
  onPreview: (file: FileItem) => void;
  onDownload: (file: FileItem) => void;
  onDelete: (file: FileItem) => void;
}) {
  return (
    <div className="group relative flex flex-col rounded-lg border border-neutral-200 bg-white p-4 transition-colors hover:bg-neutral-50">
      <div className="absolute right-2 top-2">
        <FileActions
          file={file}
          onPreview={onPreview}
          onDownload={onDownload}
          onDelete={onDelete}
        />
      </div>
      <div className="flex items-center justify-center rounded-md bg-neutral-100 py-8">
        <FileIcon extension={file.extension} className="h-12 w-12" />
      </div>
      <div className="mt-3 min-w-0">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-neutral-900" title={file.name}>
            {file.name}
          </p>
        </div>
        <div className="mt-1 flex items-center justify-between text-xs text-neutral-500">
          <span>{formatBytes(file.size)}</span>
          <span>{formatDate(file.updated_at)}</span>
        </div>
        {file.status !== "ready" ? (
          <div className="mt-2">
            <StatusBadge status={file.status} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
