// apps/web/src/app/App.tsx

import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "@tanstack/react-router"

import { createQueryClient } from "@/app/query-client"
import { createAppRouter } from "@/app/router"

const queryClient = createQueryClient()
const router = createAppRouter(queryClient)

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
