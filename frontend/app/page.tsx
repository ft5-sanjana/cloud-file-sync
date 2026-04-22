"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/features/auth/store";

export default function HomePage() {
  const router = useRouter();
  const isInitialized = useAuthStore((s) => s.isInitialized);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (!isInitialized) return;
    router.replace(user ? "/dashboard" : "/login");
  }, [isInitialized, user, router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="text-sm text-neutral-500">Loading…</div>
    </main>
  );
}
