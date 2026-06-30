// apps/web/src/app/query-client.ts

import { QueryClient } from "@tanstack/react-query"

import { ApiError } from "@/lib/api/errors"

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status < 500) {
            return false
          }
          return failureCount < 2
        },
      },
    },
  })
}
