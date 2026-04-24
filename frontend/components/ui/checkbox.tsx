"use client";

/**
 * Minimal tri-state checkbox — native <input type="checkbox"> with Tailwind
 * styling. We avoid pulling in @radix-ui/react-checkbox because the only
 * tri-state need today is the "Select all visible files" header; a native
 * input + ref-based `indeterminate` is plenty.
 *
 * Pass `state` for tri-state semantics:
 *   "unchecked" | "checked" | "indeterminate"
 * Indeterminate displays visually via the underlying DOM property and is
 * re-applied on every render (DOM checkbox state is not purely controlled).
 */

import { forwardRef, useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

export type CheckboxState = "unchecked" | "checked" | "indeterminate";

type Props = {
  state: CheckboxState;
  onToggle: () => void;
  className?: string;
  ariaLabel?: string;
  /** Stop pointer events from bubbling (e.g. row click handlers). */
  stopPropagation?: boolean;
  disabled?: boolean;
};

export const Checkbox = forwardRef<HTMLInputElement, Props>(function Checkbox(
  { state, onToggle, className, ariaLabel, stopPropagation, disabled },
  _ref,
) {
  const innerRef = useRef<HTMLInputElement | null>(null);

  // `indeterminate` is a DOM-only property, not reflected in HTML. Set it on
  // every render so state flips like "some → all → none" render correctly.
  useEffect(() => {
    if (innerRef.current) {
      innerRef.current.indeterminate = state === "indeterminate";
    }
  }, [state]);

  return (
    <input
      ref={innerRef}
      type="checkbox"
      checked={state === "checked"}
      aria-checked={state === "indeterminate" ? "mixed" : state === "checked"}
      aria-label={ariaLabel}
      disabled={disabled}
      onChange={onToggle}
      onClick={(e) => {
        if (stopPropagation) e.stopPropagation();
      }}
      className={cn(
        "h-4 w-4 cursor-pointer rounded border-neutral-300 text-neutral-900",
        "focus:ring-2 focus:ring-neutral-900 focus:ring-offset-0",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
    />
  );
});
