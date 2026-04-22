"use client";

import { FileX2 } from "lucide-react";

export function EmptyState({
  title = "No files yet",
  description = "Upload your first file to get started.",
  action,
}: {
  title?: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-neutral-300 bg-neutral-50 px-6 py-16 text-center">
      <FileX2 className="mb-4 h-10 w-10 text-neutral-400" aria-hidden />
      <h3 className="text-base font-medium text-neutral-900">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-neutral-500">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
