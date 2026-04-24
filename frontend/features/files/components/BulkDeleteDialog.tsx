"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function BulkDeleteDialog({
  count,
  open,
  onOpenChange,
  onConfirm,
  isDeleting,
}: {
  count: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isDeleting?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Delete {count} {count === 1 ? "file" : "files"}?
          </DialogTitle>
          <DialogDescription>
            {count === 1
              ? "This file will be permanently removed from your cloud storage. This cannot be undone."
              : `These ${count} files will be permanently removed from your cloud storage. This cannot be undone.`}
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
            disabled={isDeleting || count === 0}
          >
            {isDeleting
              ? "Deleting…"
              : `Delete ${count} ${count === 1 ? "file" : "files"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
