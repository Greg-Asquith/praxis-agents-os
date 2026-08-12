import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { currentUserQueryKey } from "@/features/auth/api/get-current-user"
import { platformUsageBreakdownQueryOptions } from "@/features/usage/api/get-platform-usage-breakdown"
import { platformUsageSummaryQueryOptions } from "@/features/usage/api/get-platform-usage-summary"
import { platformUsageQueryKeys } from "@/features/usage/api/query-keys"
import { usageBreakdownQueryOptions } from "@/features/usage/api/get-usage-breakdown"
import { usageSummaryQueryOptions } from "@/features/usage/api/get-usage-summary"
import { UsageSettingsPanel } from "@/features/usage/components/usage-dashboard-panel"
import type { AuthUser } from "@/features/auth/types"
import type {
  PlatformUsageBreakdown,
  UsageBreakdown,
  UsageRange,
  UsageSummary,
} from "@/features/usage/types"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

const NOW = new Date("2026-08-12T12:00:00Z")
const RANGE: UsageRange = {
  from: "2026-07-13T12:00:00.000Z",
  to: "2026-08-12T12:00:00.000Z",
}

afterEach(() => {
  setActiveUserId(null)
  setActiveWorkspaceSlug(null)
  vi.useRealTimers()
})

describe("UsageSettingsPanel", () => {
  it("keeps the workspace dashboard direct for a non-super-admin", () => {
    const html = renderUsageSettings(false)

    expect(html).toContain("AI Usage")
    expect(html).not.toContain("This Workspace")
    expect(html).not.toContain("All Workspaces")
  })

  it("adds nested workspace and platform tabs for a super admin", () => {
    const html = renderUsageSettings(true)

    expect(html).toContain("This Workspace")
    expect(html).toContain("All Workspaces")
    expect(html).toContain("AI Usage")
  })

  it("keeps platform query keys independent from the active workspace", () => {
    setActiveWorkspaceSlug("workspace-a")
    const first = platformUsageQueryKeys.summary("user-a", RANGE)
    setActiveWorkspaceSlug("workspace-b")

    expect(platformUsageQueryKeys.summary("user-a", RANGE)).toEqual(first)
  })
})

function renderUsageSettings(isSuperAdmin: boolean) {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
  setActiveUserId("user-a")
  setActiveWorkspaceSlug("workspace-a")
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user: AuthUser = {
    id: "user-a",
    email: "user-a@example.com",
    display_name: "User A",
    avatar_url: null,
    is_active: true,
    is_super_admin: isSuperAdmin,
    default_workspace_id: "workspace-a",
    totp_enabled: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  }
  queryClient.setQueryData(currentUserQueryKey, user)
  queryClient.setQueryData(usageSummaryQueryOptions(RANGE).queryKey, emptySummary())
  queryClient.setQueryData(
    usageBreakdownQueryOptions({ ...RANGE, dimension: "agent" }).queryKey,
    emptyBreakdown()
  )
  queryClient.setQueryData(
    platformUsageSummaryQueryOptions(user.id, RANGE).queryKey,
    emptySummary()
  )
  queryClient.setQueryData(
    platformUsageBreakdownQueryOptions(user.id, {
      ...RANGE,
      dimension: "workspace",
    }).queryKey,
    emptyPlatformBreakdown()
  )

  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: queryClient }, createElement(UsageSettingsPanel))
  )
}

function emptySummary(): UsageSummary {
  return {
    from: RANGE.from,
    to: RANGE.to,
    timezone: "UTC",
    totals: {
      estimated_cost_usd: "0",
      tokens_by_class: { input: 0, cache_read: 0, cache_write: 0, output: 0 },
      requests: 0,
    },
    pricing_coverage: emptyCoverage(),
    daily: [],
    models: [],
  }
}

function emptyBreakdown(): UsageBreakdown {
  return {
    from: RANGE.from,
    to: RANGE.to,
    timezone: "UTC",
    dimension: "agent",
    rows: [],
  }
}

function emptyPlatformBreakdown(): PlatformUsageBreakdown {
  return {
    from: RANGE.from,
    to: RANGE.to,
    timezone: "UTC",
    dimension: "workspace",
    rows: [],
  }
}

function emptyCoverage() {
  return {
    priced_tokens: 0,
    unpriced_tokens: 0,
    token_coverage_percent: "0",
    priced_requests: 0,
    unpriced_requests: 0,
    request_coverage_percent: "0",
    priced_image_generations: 0,
    unpriced_image_generations: 0,
  }
}
