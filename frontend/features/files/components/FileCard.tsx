"use client";

import { Checkbox, type CheckboxState } from "@/components/ui/checkbox";

import type { FileItem } from "../types";
import { formatBytes, formatDate } from "../utils";
import { FileActions } from "./FileActions";
import { FileIcon } from "./FileIcon";
import { StatusBadge } from "./StatusBadge";

export function FileCard({
  file,
  selected,
  onToggleSelect,
  onPreview,
  onDownload,
  onDelete,
}: {
  file: FileItem;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  onPreview: (file: FileItem) => void;
  onDownload: (file: FileItem) => void;
  onDelete: (file: FileItem) => void;
}) {
  const state: CheckboxState = selected ? "checked" : "unchecked";
  return (
    <div
      className={
        "group relative flex flex-col rounded-lg border bg-white p-4 transition-colors hover:bg-neutral-50 " +
        (selected ? "border-neutral-900/40 bg-neutral-50" : "border-neutral-200")
      }
    >
      <div className="absolute left-2 top-2 z-10">
        <Checkbox
          state={state}
          onToggle={() => onToggleSelect(file.id)}
          stopPropagation
          ariaLabel={`Select ${file.name}`}
        />
      </div>
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
