"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { authApi } from "@/features/auth/api";
import {
  changePasswordSchema,
  deleteAccountSchema,
  profileUpdateSchema,
} from "@/features/auth/schemas";
import { useAuthStore } from "@/features/auth/store";
import { ApiError } from "@/lib/api";

/**
 * /profile — account self-service.
 *
 * Three sections on one page to keep mental model simple:
 *   1. Profile — edit first/last name
 *   2. Change password — old + new + confirm; blacklists other sessions
 *   3. Delete account — destructive, gated behind a modal + password
 *
 * The dashboard layout already redirects unauthenticated users, so the
 * guard here is just a render-time null-check.
 */
export default function ProfilePage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const setSession = useAuthStore((s) => s.setSession);
  const clear = useAuthStore((s) => s.clear);

  if (!user) return null;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
          <p className="text-sm text-neutral-500">Manage your account.</p>
        </div>
        <Button variant="outline" asChild>
          <Link href="/dashboard">Back to files</Link>
        </Button>
      </header>

      <ProfileForm
        initialFirstName={user.first_name}
        initialLastName={user.last_name}
        email={user.email}
        onSaved={(u) => setUser(u)}
      />

      <ChangePasswordForm
        onChanged={(token, u) => setSession(token, u)}
      />

      <DeleteAccountCard
        onDeleted={() => {
          clear();
          router.replace("/login");
        }}
      />
    </div>
  );
}

// ─── Profile form ────────────────────────────────────────────────
function ProfileForm({
  initialFirstName,
  initialLastName,
  email,
  onSaved,
}: {
  initialFirstName: string;
  initialLastName: string;
  email: string;
  onSaved: (user: import("@/features/auth/types").User) => void;
}) {
  const [firstName, setFirstName] = useState(initialFirstName);
  const [lastName, setLastName] = useState(initialLastName);
  const [errors, setErrors] = useState<{ first_name?: string; last_name?: string }>({});

  const mutation = useMutation({
    mutationFn: authApi.updateProfile,
    onSuccess: (updated) => {
      onSaved(updated);
      toast.success("Profile updated.");
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError) {
        toast.error(error.message || "Could not update profile.");
      } else {
        toast.error("Could not update profile.");
      }
    },
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = profileUpdateSchema.safeParse({
      first_name: firstName,
      last_name: lastName,
    });
    if (!parsed.success) {
      const fieldErrors: typeof errors = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as "first_name" | "last_name" | undefined;
        if (key) fieldErrors[key] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    mutation.mutate(parsed.data);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account details</CardTitle>
        <CardDescription>
          Your email is <span className="font-medium">{email}</span>. Name changes are saved immediately.
        </CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="first_name">First name</Label>
              <Input
                id="first_name"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                aria-invalid={Boolean(errors.first_name)}
              />
              {errors.first_name && <p className="text-xs text-red-600">{errors.first_name}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="last_name">Last name</Label>
              <Input
                id="last_name"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                aria-invalid={Boolean(errors.last_name)}
              />
              {errors.last_name && <p className="text-xs text-red-600">{errors.last_name}</p>}
            </div>
          </div>
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save changes"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

// ─── Change password form ────────────────────────────────────────
function ChangePasswordForm({
  onChanged,
}: {
  onChanged: (accessToken: string, user: import("@/features/auth/types").User) => void;
}) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [errors, setErrors] = useState<{
    old_password?: string;
    new_password?: string;
    confirm_new_password?: string;
  }>({});

  const mutation = useMutation({
    mutationFn: authApi.changePassword,
    onSuccess: (resp) => {
      // Server re-issues a fresh access token + refresh cookie. Sync the
      // store so the next request uses the new access token.
      onChanged(resp.access, resp.user);
      setOldPassword("");
      setNewPassword("");
      setConfirmNewPassword("");
      toast.success("Password updated. Other sessions have been signed out.");
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError) {
        if (error.code === "INVALID_OLD_PASSWORD") {
          setErrors({ old_password: "Current password is incorrect." });
        } else if (error.code === "WEAK_PASSWORD") {
          setErrors({ new_password: error.message });
        } else if (error.code === "SAME_PASSWORD") {
          setErrors({ new_password: error.message });
        } else if (error.code === "RATE_LIMITED") {
          toast.error("Too many password change attempts. Try again later.");
        } else {
          toast.error(error.message || "Could not change password.");
        }
      } else {
        toast.error("Could not change password.");
      }
    },
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = changePasswordSchema.safeParse({
      old_password: oldPassword,
      new_password: newPassword,
      confirm_new_password: confirmNewPassword,
    });
    if (!parsed.success) {
      const fieldErrors: typeof errors = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as keyof typeof errors | undefined;
        if (key) fieldErrors[key] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    mutation.mutate(parsed.data);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>
          Other devices will be signed out after a successful change.
        </CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="old_password">Current password</Label>
            <Input
              id="old_password"
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              aria-invalid={Boolean(errors.old_password)}
            />
            {errors.old_password && <p className="text-xs text-red-600">{errors.old_password}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_password">New password</Label>
            <Input
              id="new_password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              aria-invalid={Boolean(errors.new_password)}
            />
            {errors.new_password && <p className="text-xs text-red-600">{errors.new_password}</p>}
            <p className="text-xs text-neutral-500">Minimum 8 characters.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm_new_password">Confirm new password</Label>
            <Input
              id="confirm_new_password"
              type="password"
              autoComplete="new-password"
              value={confirmNewPassword}
              onChange={(e) => setConfirmNewPassword(e.target.value)}
              aria-invalid={Boolean(errors.confirm_new_password)}
            />
            {errors.confirm_new_password && (
              <p className="text-xs text-red-600">{errors.confirm_new_password}</p>
            )}
          </div>
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Updating…" : "Update password"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

// ─── Delete account ──────────────────────────────────────────────
function DeleteAccountCard({ onDeleted }: { onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: authApi.deleteAccount,
    onSuccess: () => {
      toast.success("Account deleted.");
      setOpen(false);
      onDeleted();
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError) {
        if (err.code === "INVALID_PASSWORD") {
          setError("Password is incorrect.");
        } else if (err.code === "RATE_LIMITED") {
          toast.error("Too many attempts. Try again later.");
        } else {
          toast.error(err.message || "Could not delete account.");
        }
      } else {
        toast.error("Could not delete account.");
      }
    },
  });

  function onConfirm() {
    const parsed = deleteAccountSchema.safeParse({ password });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Password is required.");
      return;
    }
    setError(null);
    mutation.mutate(parsed.data);
  }

  return (
    <>
      <Card className="border-red-200">
        <CardHeader>
          <CardTitle className="text-red-700">Danger zone</CardTitle>
          <CardDescription>
            Permanently delete your account, all your files, and all associated data. This action cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Button
            variant="outline"
            className="border-red-300 text-red-700 hover:bg-red-50"
            onClick={() => {
              setPassword("");
              setError(null);
              setOpen(true);
            }}
          >
            Delete my account
          </Button>
        </CardFooter>
      </Card>

      <Dialog open={open} onOpenChange={(v) => !mutation.isPending && setOpen(v)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete your account?</DialogTitle>
            <DialogDescription>
              This will permanently remove your files from storage, wipe your metadata, and sign you out from every device. You&apos;ll need to register again to use the service.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="delete_password">Enter your password to confirm</Label>
            <Input
              id="delete_password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={Boolean(error)}
            />
            {error && <p className="text-xs text-red-600">{error}</p>}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              onClick={onConfirm}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Deleting…" : "Delete account"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
