"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthStore } from "@/features/auth/store";

/**
 * Shell for /login and /register.
 * If an initialized session exists, bounce to the dashboard.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const isInitialized = useAuthStore((s) => s.isInitialized);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (isInitialized && user) router.replace("/dashboard");
  }, [isInitialized, user, router]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-neutral-50 p-4">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Cloud File Sync</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Secure private file storage.
        </p>
      </div>
      {children}
    </main>
  );
}
