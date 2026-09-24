"use client";

import * as React from "react";
import { SWRConfig } from "swr";
import { ApiError, request } from "@/lib/api/client";
import { ThemeProvider } from "@/components/theme";
import { AuthSessionBoundary } from "@/features/auth/AuthSessionBoundary";

const apiFetcher = (path: string) => request<unknown>("GET", path);

export function shouldRetryApiError(error: unknown): boolean {
  return !(error instanceof ApiError && [401, 403, 404].includes(error.status));
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <SWRConfig
        value={{
          fetcher: apiFetcher,
          revalidateOnFocus: false,
          shouldRetryOnError: shouldRetryApiError,
          errorRetryCount: 2,
        }}
      >
        <AuthSessionBoundary>{children}</AuthSessionBoundary>
      </SWRConfig>
    </ThemeProvider>
  );
}
