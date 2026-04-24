"use client";

/**
 * Confirmation modal for folder deletion. Folder deletes cascade into
 * every file/subfolder beneath — we spell that out loudly so the user
 * can't click through without understanding what happens.
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { FolderItem } from "../types";

export function DeleteFolderDialog({
  folder,
  open,
  onOpenChange,
  onConfirm,
  isDeleting,
}: {
  folder: FolderItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isDeleting?: boolean;
}) {
  const entryCount = folder ? folder.file_count + folder.subfolder_count : 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete folder?</DialogTitle>
          <DialogDescription>
            {folder
              ? `“${folder.name}” ` +
                (entryCount > 0
                  ? `and everything inside (${folder.file_count} file${folder.file_count === 1 ? "" : "s"}` +
                    (folder.subfolder_count > 0
                      ? `, ${folder.subfolder_count} subfolder${folder.subfolder_count === 1 ? "" : "s"}`
                      : "") +
                    ") will be permanently removed. This cannot be undone."
                  : "will be permanently removed. This cannot be undone.")
              : "This folder will be permanently removed."}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isDeleting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={isDeleting}
          >
            {isDeleting ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
