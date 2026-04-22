"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * Global error boundary — catches unhandled render/runtime errors in any
 * route segment that doesn't supply its own error.tsx. Keeps the UI alive
 * instead of showing a blank page.
 *
 * Next.js injects `error` (with optional `digest` in prod) and `reset`.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface in the console for dev; a real deploy would ship to an error
    // reporter here (Sentry, etc).
    // eslint-disable-next-line no-console
    console.error("Unhandled app error:", error);
  }, [error]);

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-xl font-semibold tracking-tight">
        Something went wrong
      </h1>
      <p className="text-sm text-neutral-500">
        An unexpected error occurred. You can try again, or reload the page if
        the problem persists.
      </p>
      {error.digest ? (
        <p className="font-mono text-xs text-neutral-400">
          Reference: {error.digest}
        </p>
      ) : null}
      <div className="mt-2 flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Button
          variant="outline"
          onClick={() => {
            window.location.href = "/";
          }}
        >
          Go home
        </Button>
      </div>
    </div>
  );
}
