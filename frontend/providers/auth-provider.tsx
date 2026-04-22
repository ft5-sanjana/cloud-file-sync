"use client";

/**
 * On first mount, try to reconstitute a session:
 *   1. POST /api/auth/refresh using the HttpOnly refresh cookie
 *   2. If that returns an access token, GET /api/auth/me
 *   3. Mark the store as initialized either way, so route guards can decide
 *
 * Does not block rendering — guards show a lightweight loader while
 * `isInitialized` is false.
 */
import { useEffect } from "react";

import { authApi } from "@/features/auth/api";
import { useAuthStore } from "@/features/auth/store";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const setSession = useAuthStore((s) => s.setSession);
  const setInitialized = useAuthStore((s) => s.setInitialized);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const res = await fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "include",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!res.ok) return;
        const { access } = (await res.json()) as { access: string };
        if (cancelled) return;

        // Put the token in the store before calling /me so apiFetch attaches it.
        useAuthStore.getState().setAccessToken(access);
        const user = await authApi.me();
        if (cancelled) return;

        setSession(access, user);
      } catch {
        // No active session. Leave store empty.
      } finally {
        if (!cancelled) setInitialized(true);
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>{children}</>;
}
