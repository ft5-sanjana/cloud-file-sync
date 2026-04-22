"use client";

import type { FileItem } from "../types";
import { formatBytes, formatDate } from "../utils";
import { FileActions } from "./FileActions";
import { FileIcon } from "./FileIcon";
import { StatusBadge } from "./StatusBadge";

export function FileRow({
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
    <div className="flex items-center gap-3 rounded-md border border-neutral-200 bg-white px-3 py-2 transition-colors hover:bg-neutral-50">
      <FileIcon extension={file.extension} className="h-6 w-6 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-neutral-900">{file.name}</p>
          <StatusBadge status={file.status} />
        </div>
        <p className="mt-0.5 truncate text-xs text-neutral-500">
          {formatBytes(file.size)} · {formatDate(file.updated_at)}
        </p>
      </div>
      <FileActions
        file={file}
        onPreview={onPreview}
        onDownload={onDownload}
        onDelete={onDelete}
      />
    </div>
  );
}
