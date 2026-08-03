// apps/web/src/app/App.tsx

import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "@tanstack/react-router"

import { createQueryClient } from "@/app/query-client"
import { createAppRouter } from "@/app/router"
import { installSessionLossHandler } from "@/features/auth/session-loss"

const queryClient = createQueryClient()
const router = createAppRouter(queryClient)
installSessionLossHandler(queryClient, () => router.invalidate())

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
