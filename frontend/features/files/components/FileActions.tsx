"use client";

import { Download, Eye, MoreVertical, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { isPreviewable } from "../utils";
import type { FileItem } from "../types";

export function FileActions({
  file,
  onPreview,
  onDownload,
  onDelete,
  disabled,
}: {
  file: FileItem;
  onPreview: (file: FileItem) => void;
  onDownload: (file: FileItem) => void;
  onDelete: (file: FileItem) => void;
  disabled?: boolean;
}) {
  const canPreview = isPreviewable(file.extension);
  const ready = file.status === "ready";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          disabled={disabled}
          aria-label={`Actions for ${file.name}`}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {canPreview ? (
          <DropdownMenuItem
            disabled={!ready}
            onSelect={() => onPreview(file)}
          >
            <Eye className="h-4 w-4" />
            Preview
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem
          disabled={!ready}
          onSelect={() => onDownload(file)}
        >
          <Download className="h-4 w-4" />
          Download
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          onSelect={() => onDelete(file)}
        >
          <Trash2 className="h-4 w-4" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
