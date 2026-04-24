"use client";

/**
 * Folder-path breadcrumb. Always starts with a "Home" root node that
 * navigates to the top level (folderId = null). Intermediate crumbs are
 * clickable, the final segment is rendered as plain text.
 *
 * The caller supplies the trail as an ordered list of ancestors ending
 * with the current folder. Producing the trail from the ancestor chain
 * (not from the `path` string) means we carry real folder IDs for each
 * crumb — no extra lookup round-trip needed on click.
 */

import { ChevronRight, Home } from "lucide-react";

export type BreadcrumbItem = {
  id: string;
  name: string;
};

export function Breadcrumb({
  trail,
  onNavigate,
}: {
  /** Ordered ancestors from shallowest to current. Empty = at root. */
  trail: BreadcrumbItem[];
  /** Called with a folder id, or null for root. */
  onNavigate: (folderId: string | null) => void;
}) {
  return (
    <nav
      aria-label="Folder path"
      className="flex flex-wrap items-center gap-1 text-sm text-neutral-600"
    >
      <button
        type="button"
        onClick={() => onNavigate(null)}
        className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-neutral-100 hover:text-neutral-900"
      >
        <Home className="h-3.5 w-3.5" aria-hidden />
        <span>Home</span>
      </button>
      {trail.map((item, i) => {
        const isLast = i === trail.length - 1;
        return (
          <div key={item.id} className="flex items-center gap-1">
            <ChevronRight className="h-3.5 w-3.5 text-neutral-400" aria-hidden />
            {isLast ? (
              <span
                className="truncate px-2 py-1 font-medium text-neutral-900"
                title={item.name}
                aria-current="page"
              >
                {item.name}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onNavigate(item.id)}
                className="truncate rounded px-2 py-1 hover:bg-neutral-100 hover:text-neutral-900"
                title={item.name}
              >
                {item.name}
              </button>
            )}
          </div>
        );
      })}
    </nav>
  );
}
