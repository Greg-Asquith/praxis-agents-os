import type * as ReactQuery from "@tanstack/react-query"
import type * as EntityQueries from "@/components/tool-ui/entity-reference-queries"
import { createElement, isValidElement, type ComponentProps } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryObserver } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { lookupEntityReferences } from "@/components/tool-ui/entity-reference-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import type { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import { approvalDisplayQueryOptions } from "@/integrations/approval-display-query"
import type { RefreshedWriteApproval } from "@/integrations/refreshed-write-approval"
import { refreshBudgetAssignment } from "@/integrations/google_ads/api/refresh-budget-assignment"
import { googleAdsAssignCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/assign-campaign-budgets"

const query = vi.hoisted(() => {
  const result: { data: unknown; isPending: boolean; isFetching: boolean; isError: boolean } = {
    data: undefined,
    isPending: true,
    isFetching: true,
    isError: false,
  }
  return { result, options: vi.fn() }
})

vi.mock("@tanstack/react-query", async (load) => ({
  ...(await load<typeof ReactQuery>()),
  useQuery: (options: unknown) => {
    query.options(options)
    return query.result
  },
}))
vi.mock("@/components/tool-ui/entity-reference-queries", async (load) => ({
  ...(await load<typeof EntityQueries>()),
  lookupEntityReferences: vi.fn(),
}))
afterEach(() => vi.clearAllMocks())

function budget(id: string) {
  return {
    amount_micros: 10_000_000,
    budget_id: id,
    campaign_labels: [],
    currency_code: "GBP",
    delivery_method: "STANDARD",
    entity_kind: "google_ads_campaign_budget",
    explicitly_shared: true,
    customer_id: "1234567890",
    label: `Budget ${id}`,
    period: "DAILY",
    reference_count: 1,
    status: "ENABLED",
    total_amount_micros: null,
    version: 1,
  }
}
function campaign(id: string) {
  return {
    campaign_id: id,
    campaign_budget_id: `5${id}`,
    customer_id: "1234567890",
    entity_kind: "google_ads_campaign",
    label: `Campaign ${id}`,
    version: 1,
  }
}
const original = {
  campaigns: [campaign("1"), campaign("2")],
  destination_budget: budget("90"),
  _budget_routes: ["1", "2"].map((id) => ({
    campaign: campaign(id),
    previous_budget: budget(`5${id}`),
    destination_budget: budget("90"),
  })),
}
function mockLookup() {
  vi.mocked(lookupEntityReferences).mockImplementation((request) =>
    Promise.resolve({
      entity_kind:
        request.fieldKey === "campaigns" ? "google_ads_campaign" : "google_ads_campaign_budget",
      choices: (request.exactValues ?? []).toReversed().map((value) => {
        const reference =
          request.fieldKey === "campaigns"
            ? campaign(String(value["campaign_id"]))
            : budget(String(value["budget_id"]))
        return {
          identity: [reference.customer_id, reference.label],
          value: reference,
          label: reference.label,
          description: null,
          scope_label: null,
        }
      }),
      next_cursor: null,
    })
  )
}
function controls(): ToolApprovalDecisionControls {
  return {
    decision: {
      decision: "pending",
      edits: { campaigns: [campaign("3")], destination_budget: budget("91") },
      message: "",
    },
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 2,
    submitting: false,
  }
}
function presenter(decision = controls()) {
  return googleAdsAssignCampaignBudgetsPresenter.render({
    activity: {
      id: "assignment",
      name: "google_ads_assign_campaign_budgets",
      kind: "approval",
      status: "awaiting_approval",
      args: original,
    },
    approvalDecision: decision,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
  })
}
function html(decision = controls()) {
  return renderToStaticMarkup(
    createElement(ToolConversationContext, { value: "conversation" }, presenter(decision))
  )
}

describe("budget assignment selection refresh", () => {
  it.each([
    { ids: ["1", "2"], destination: "91" },
    { ids: ["1", "2", "3"], destination: "90" },
    { ids: ["2"], destination: "90" },
    { ids: ["2", "1"], destination: "90" },
  ])(
    "refreshes destination and ordered campaigns $ids / $destination",
    async ({ ids, destination }) => {
      mockLookup()
      const signal = new AbortController().signal
      const value = {
        ...original,
        campaigns: ids.map(campaign),
        destination_budget: budget(destination),
      }
      const result = await refreshBudgetAssignment(value, "conversation", signal)
      expect(result["campaigns"]).toEqual(ids.map(campaign))
      expect(result["destination_budget"]).toEqual(budget(destination))
      expect(result["_budget_routes"]).toEqual(
        ids.map((id) => ({
          campaign: campaign(id),
          previous_budget: budget(`5${id}`),
          destination_budget: budget(destination),
        }))
      )
      expect(lookupEntityReferences).toHaveBeenCalledTimes(3)
      for (const call of vi.mocked(lookupEntityReferences).mock.calls) {
        expect(call[0].conversationId).toBe("conversation")
        expect(call[1]).toBe(signal)
      }
    }
  )
  it("fails when a live campaign is missing", async () => {
    mockLookup()
    vi.mocked(lookupEntityReferences).mockResolvedValueOnce({
      entity_kind: "google_ads_campaign",
      choices: [],
      next_cursor: null,
    })
    await expect(
      refreshBudgetAssignment(original, "conversation", new AbortController().signal)
    ).rejects.toThrow("Selected target unavailable")
  })
  it("requires verified source budgets instead of client references", async () => {
    mockLookup()
    const implementation = vi.mocked(lookupEntityReferences).getMockImplementation()
    if (!implementation) throw new Error("Missing lookup fixture")
    vi.mocked(lookupEntityReferences).mockImplementation((request, signal) => {
      if (request.exactValues?.some((value) => value["budget_id"] === "51")) {
        return Promise.resolve({
          entity_kind: "google_ads_campaign_budget",
          choices: [],
          next_cursor: null,
        })
      }
      return implementation(request, signal)
    })
    await expect(
      refreshBudgetAssignment(original, "conversation", new AbortController().signal)
    ).rejects.toThrow("Source budget unavailable")
  })
  it("propagates a provider read failure without returning retained routes", async () => {
    mockLookup()
    vi.mocked(lookupEntityReferences).mockRejectedValueOnce(new Error("Read failed"))
    await expect(
      refreshBudgetAssignment(original, "conversation", new AbortController().signal)
    ).rejects.toThrow("Read failed")
  })
  it.each(["pending", "failure"])("blocks approval and hides stale routes during %s", (state) => {
    query.result = {
      data: undefined,
      isPending: state === "pending",
      isFetching: state === "pending",
      isError: state === "failure",
    }
    const result = html()
    expect(result).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Assign<\/button>/)
    expect(result).not.toContain("Budget 90")
    expect(result).not.toContain("Campaign 1")
    expect(result).toContain(
      state === "pending" ? "Checking the selected details" : "couldn&#x27;t be refreshed"
    )
  })
  it("shows verified routes for the submitted selection and preserves its edits", async () => {
    mockLookup()
    const decision = controls()
    const data = await refreshBudgetAssignment(
      { ...original, ...decision.decision.edits },
      "conversation",
      new AbortController().signal
    )
    query.result = { data, isPending: false, isFetching: false, isError: false }
    const result = html(decision)
    expect(result).toContain("Campaign 3")
    expect(result).toContain("Budget 53")
    expect(result).toContain("Budget 91")
    expect(result).not.toContain("Budget 90")
    expect(result).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Assign<\/button>/)
    const node = presenter(decision)
    if (!isValidElement<ComponentProps<typeof RefreshedWriteApproval>>(node))
      throw new Error("Missing refresh")
    const card = node.props.children(data, null)
    if (!isValidElement<ComponentProps<typeof ToolApprovalDecisionCard>>(card))
      throw new Error("Missing approval")
    expect(card.props.controls.decision.edits).toEqual(decision.decision.edits)
    expect(decision.onDecisionChange).not.toHaveBeenCalled()
  })
  it.each(["approved", "denied"] as const)(
    "does not refresh or reset a %s decision",
    (decision) => {
      const control = controls()
      control.decision = { decision, edits: control.decision.edits, message: "" }
      query.result = { data: original, isPending: false, isFetching: false, isError: false }
      html(control)
      expect(query.options).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: false }))
      expect(control.onDecisionChange).not.toHaveBeenCalled()
    }
  )
  it("ignores a late response for an earlier selection", async () => {
    const client = new QueryClient()
    let finishOld: ((value: Record<string, unknown>) => void) | undefined
    const refresh = vi.fn((args: unknown) =>
      args === "old"
        ? new Promise<Record<string, unknown>>((resolve) => {
            finishOld = resolve
          })
        : Promise.resolve({ selection: "latest" })
    )
    const observer = new QueryObserver(
      client,
      approvalDisplayQueryOptions("old", "conversation", "assign", refresh)
    )
    const unsubscribe = observer.subscribe(vi.fn())
    observer.setOptions(approvalDisplayQueryOptions("latest", "conversation", "assign", refresh))
    await vi.waitFor(() => {
      expect(observer.getCurrentResult().data).toEqual({ selection: "latest" })
    })
    finishOld?.({ selection: "old" })
    await Promise.resolve()
    expect(observer.getCurrentResult().data).toEqual({ selection: "latest" })
    unsubscribe()
    client.clear()
  })
})
