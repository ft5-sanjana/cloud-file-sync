"use client";

/**
 * Dropdown menu for folder-level actions. Mirrors FileActions shape so
 * the list/grid views feel consistent — download triggers a ZIP via the
 * token-signed flow; delete cascades via the folder-delete endpoint.
 *
 * Callers own the actual side effects (mutations, toasts, state). This
 * component is presentational.
 */

import { Download, MoreVertical, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import type { FolderItem } from "../types";

export function FolderActions({
  folder,
  onDownload,
  onDelete,
  disabled,
}: {
  folder: FolderItem;
  onDownload: (folder: FolderItem) => void;
  onDelete: (folder: FolderItem) => void;
  disabled?: boolean;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          disabled={disabled}
          aria-label={`Actions for folder ${folder.name}`}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => onDownload(folder)}>
          <Download className="h-4 w-4" />
          Download as ZIP
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => onDelete(folder)}>
          <Trash2 className="h-4 w-4" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
