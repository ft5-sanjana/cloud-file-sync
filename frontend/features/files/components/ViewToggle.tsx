"use client";

import { LayoutGrid, List } from "lucide-react";

import { cn } from "@/lib/utils";

export type ViewMode = "list" | "grid";

export function ViewToggle({
  mode,
  onChange,
}: {
  mode: ViewMode;
  onChange: (m: ViewMode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Toggle file view"
      className="inline-flex rounded-md border border-neutral-200 bg-white p-0.5"
    >
      <button
        type="button"
        role="tab"
        aria-selected={mode === "list"}
        onClick={() => onChange("list")}
        className={cn(
          "inline-flex h-8 w-8 items-center justify-center rounded text-neutral-600 transition-colors",
          mode === "list" ? "bg-neutral-900 text-white" : "hover:bg-neutral-100",
        )}
        aria-label="List view"
      >
        <List className="h-4 w-4" />
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === "grid"}
        onClick={() => onChange("grid")}
        className={cn(
          "inline-flex h-8 w-8 items-center justify-center rounded text-neutral-600 transition-colors",
          mode === "grid" ? "bg-neutral-900 text-white" : "hover:bg-neutral-100",
        )}
        aria-label="Grid view"
      >
        <LayoutGrid className="h-4 w-4" />
      </button>
    </div>
  );
}
