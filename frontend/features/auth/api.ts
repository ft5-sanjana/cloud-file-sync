import { apiFetch } from "@/lib/api";

import type { LoginInput, RegisterInput } from "./schemas";
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
};
