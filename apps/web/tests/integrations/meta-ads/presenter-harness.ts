// apps/web/tests/integrations/meta-ads/presenter-harness.ts

import { createElement, type ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"

export const APPROVE_DISABLED = /<button[^>]*\sdisabled=""[^>]*>Approve/

export function props(activity: ToolActivity, withApproval = false) {
  return {
    activity,
    ...(withApproval
      ? {
          approvalDecision: {
            decision: { decision: "pending" as const, edits: {}, message: "" as const },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
        }
      : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "meta_ads",
  }
}

export function render(node: ReactNode) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement("div", null, node)
    )
  )
}
