import { apiFetch } from "@/lib/api";

import type {
  ChangePasswordInput,
  DeleteAccountInput,
  LoginInput,
  ProfileUpdateInput,
  RegisterInput,
} from "./schemas";
import type { RegisterResponse, TokenResponse, User } from "./types";

export const authApi = {
  register(input: RegisterInput): Promise<RegisterResponse> {
    return apiFetch<RegisterResponse>("/api/auth/register", {
      method: "POST",
      body: input,
      skipAuth: true,
      skipRefresh: true,
    });
  },

  login(input: LoginInput): Promise<TokenResponse> {
    return apiFetch<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: input,
      skipAuth: true,
      skipRefresh: true,
    });
  },

  logout(): Promise<void> {
    return apiFetch<void>("/api/auth/logout", { method: "POST" });
  },

  me(): Promise<User> {
    return apiFetch<User>("/api/auth/me", { method: "GET" });
  },

  updateProfile(input: ProfileUpdateInput): Promise<User> {
    return apiFetch<User>("/api/auth/me", { method: "PATCH", body: input });
  },

  changePassword(input: ChangePasswordInput): Promise<TokenResponse> {
    return apiFetch<TokenResponse>("/api/auth/change-password", {
      method: "POST",
      body: input,
    });
  },

  deleteAccount(input: DeleteAccountInput): Promise<void> {
    // POST (not DELETE) because some proxies strip bodies from DELETE — the
    // password confirmation has to ride in the body. Matches backend route.
    return apiFetch<void>("/api/auth/delete-account", {
      method: "POST",
      body: input,
    });
  },
};
