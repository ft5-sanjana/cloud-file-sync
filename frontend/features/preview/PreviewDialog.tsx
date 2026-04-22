"use client";

import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { filesApi } from "@/features/files/api";
import type { FileItem } from "@/features/files/types";
import { getFileKind } from "@/features/files/utils";

export function PreviewDialog({
  file,
  open,
  onOpenChange,
}: {
  file: FileItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !file) {
      setUrl(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    filesApi
      .signedUrl(file.id, "preview")
      .then((res) => {
        if (!cancelled) setUrl(res.url);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "Failed to load preview");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, file]);

  const kind = file ? getFileKind(file.extension) : "other";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{file?.name ?? "Preview"}</DialogTitle>
          <DialogDescription>
            {kind === "image" ? "Image preview" : kind === "pdf" ? "PDF preview" : "Preview"}
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-[60vh] items-center justify-center overflow-hidden rounded-md bg-neutral-100">
          {loading ? (
            <Skeleton className="h-[60vh] w-full" />
          ) : error ? (
            <p className="p-6 text-sm text-red-600">{error}</p>
          ) : url && kind === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={url}
              alt={file?.name ?? ""}
              className="max-h-[75vh] w-auto object-contain"
            />
          ) : url && kind === "pdf" ? (
            <iframe
              src={url}
              title={file?.name ?? "PDF preview"}
              className="h-[75vh] w-full border-0"
            />
          ) : (
            <p className="p-6 text-sm text-neutral-500">Preview unavailable for this file type.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
