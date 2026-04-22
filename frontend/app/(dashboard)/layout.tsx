"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/features/auth/store";

/**
 * Client-side guard: once initial auth bootstrap is done, redirect
 * unauthenticated users to /login. The API is the real security boundary —
 * this just keeps the UI coherent.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const isInitialized = useAuthStore((s) => s.isInitialized);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (isInitialized && !user) router.replace("/login");
  }, [isInitialized, user, router]);

  if (!isInitialized || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-neutral-500">Loading…</div>
      </main>
    );
  }

  return <div className="min-h-screen bg-neutral-50">{children}</div>;
}
