"use client";

/**
 * Modal for creating a new folder under a given parent. Mirrors the
 * pattern established by DeleteConfirmDialog — dumb-ish presentational
 * component, all mutation state owned by the caller via props.
 *
 * Client-side validation is intentionally shallow: we surface a friendly
 * error for the obvious traps (empty, slash, too long) so the user gets
 * instant feedback, but the backend's validate_folder_name remains the
 * canonical source of truth. Anything we miss here will come back as
 * FOLDER_NAME_INVALID with a clear message the hook layer shows as a
 * toast.
 */

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Keep in sync with backend MAX_FOLDER_NAME_LENGTH (255 chars). The
// backend is authoritative; this just short-circuits obvious misuse.
const MAX_FOLDER_NAME_LENGTH = 255;

function quickValidate(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "Folder name is required.";
  if (trimmed.length > MAX_FOLDER_NAME_LENGTH) {
    return `Folder name must be ${MAX_FOLDER_NAME_LENGTH} characters or fewer.`;
  }
  if (/[\\/\x00]/.test(trimmed)) {
    return "Folder names can't contain slashes.";
  }
  if (trimmed === "." || trimmed === "..") {
    return "Folder name can't be “.” or “..”.";
  }
  return null;
}

export function CreateFolderDialog({
  open,
  onOpenChange,
  onConfirm,
  isPending,
  parentName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the trimmed name. Parent dialog-owner fires the mutation. */
  onConfirm: (name: string) => void;
  isPending?: boolean;
  /** Display-only. Shown in the description so the user knows where the
   *  folder will land. Undefined = at root. */
  parentName?: string | null;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Reset local state every time the dialog opens. Closing without
  // submitting is equivalent to a fresh start next time.
  useEffect(() => {
    if (open) {
      setName("");
      setError(null);
    }
  }, [open]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const msg = quickValidate(name);
    if (msg) {
      setError(msg);
      return;
    }
    onConfirm(name.trim());
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New folder</DialogTitle>
            <DialogDescription>
              {parentName
                ? `Create a new folder inside “${parentName}”.`
                : "Create a new folder at the top level."}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-2">
            <Label htmlFor="folder-name">Name</Label>
            <Input
              id="folder-name"
              autoFocus
              value={name}
              maxLength={MAX_FOLDER_NAME_LENGTH}
              placeholder="e.g. Contracts"
              onChange={(e) => {
                setName(e.target.value);
                if (error) setError(null);
              }}
              disabled={isPending}
              aria-invalid={error ? "true" : undefined}
              aria-describedby={error ? "folder-name-error" : undefined}
            />
            {error ? (
              <p
                id="folder-name-error"
                role="alert"
                className="text-xs text-red-600"
              >
                {error}
              </p>
            ) : null}
          </div>

          <DialogFooter className="mt-6">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending || !name.trim()}>
              {isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
