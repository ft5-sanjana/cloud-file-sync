"use client";

import { cn } from "@/lib/utils";
import type { FileStatus } from "../types";

const LABEL: Record<FileStatus, string> = {
  uploading: "Uploading",
  ready: "Ready",
  failed: "Failed",
  deleting: "Deleting",
};

const STYLE: Record<FileStatus, string> = {
  uploading: "bg-blue-50 text-blue-700 ring-blue-200",
  ready: "bg-green-50 text-green-700 ring-green-200",
  failed: "bg-red-50 text-red-700 ring-red-200",
  deleting: "bg-neutral-100 text-neutral-600 ring-neutral-200",
};

export function StatusBadge({
  status,
  className,
}: {
  status: FileStatus;
  className?: string;
}) {
  if (status === "ready") return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        STYLE[status],
        className,
      )}
    >
      {LABEL[status]}
    </span>
  );
}
