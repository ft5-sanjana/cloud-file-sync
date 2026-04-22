"use client";

import { create } from "zustand";

import type { User } from "./types";

/**
 * Auth session state — held ONLY in memory.
 *
 * Why not localStorage: access tokens in localStorage are readable by any
 * JS on the page, making them an XSS exfiltration target. The refresh
 * token lives in an HttpOnly cookie (inaccessible to JS); on hard reload
 * the app re-obtains an access token by calling /api/auth/refresh.
 */
type AuthState = {
  accessToken: string | null;
  user: User | null;
  /** true once initial bootstrap (refresh attempt + /me) has completed */
  isInitialized: boolean;

  setAccessToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  setSession: (token: string, user: User) => void;
  setInitialized: (value: boolean) => void;
  clear: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isInitialized: false,

  setAccessToken: (token) => set({ accessToken: token }),
  setUser: (user) => set({ user }),
  setSession: (accessToken, user) => set({ accessToken, user }),
  setInitialized: (value) => set({ isInitialized: value }),
  clear: () => set({ accessToken: null, user: null }),
}));

export const isAuthenticated = (): boolean =>
  Boolean(useAuthStore.getState().accessToken && useAuthStore.getState().user);
