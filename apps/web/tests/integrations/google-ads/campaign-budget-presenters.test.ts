import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolUi, ToolUiField } from "@/features/tools/types"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import { googleAdsAssignCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/assign-campaign-budgets"
import { googleAdsCreateCampaignBudgetPresenter } from "@/integrations/google_ads/presenters/create-campaign-budget"
import { googleAdsRemoveCampaignBudgetsPresenter } from "@/integrations/google_ads/presenters/remove-campaign-budgets"
import { googleAdsUpdateCampaignBudgetAmountsPresenter } from "@/integrations/google_ads/presenters/update-campaign-budget-amounts"

describe("Google Ads campaign budget presenters", () => {
  it.each([
    [
      googleAdsUpdateCampaignBudgetAmountsPresenter,
      "google_ads_update_campaign_budget_amounts",
      { updates: [{ budget: budgetReference("55", "Brand budget"), amount: "12.50" }] },
      "Brand budget",
    ],
    [
      googleAdsAssignCampaignBudgetsPresenter,
      "google_ads_assign_campaign_budgets",
      {
        campaigns: [campaignReference("10", "Brand campaign")],
        destination_budget: budgetReference("55", "Shared budget"),
        _budget_routes: [
          {
            campaign: campaignReference("10", "Brand campaign"),
            previous_budget: budgetReference("54", "Old budget"),
            destination_budget: budgetReference("55", "Shared budget"),
          },
        ],
      },
      "Brand campaign",
    ],
    [
      googleAdsRemoveCampaignBudgetsPresenter,
      "google_ads_remove_campaign_budgets",
      { budgets: [budgetReference("55", "Unused budget", { reference_count: 0 })] },
      "Unused budget",
    ],
  ] as const)("shows selected labels for failed %s", (presenter, name, args, label) => {
    const html = render(presenter.render(props(activity(name, "failed", args))))
    expect(html).toMatch(new RegExp(`data-slot="badge"[^>]*>${label}</span>`))
  })

  it("shows trusted account currencies in the create approval", () => {
    const html = render(
      googleAdsCreateCampaignBudgetPresenter.render(
        props(
          activity("google_ads_create_campaign_budget", "awaiting_approval", {
            _account_currencies: [
              { label: "UK account", currency_code: "GBP" },
              { label: "EU account", currency_code: "EUR" },
            ],
            amount: { daily_amount: "12.50" },
            delivery_method: "STANDARD",
            explicitly_shared: true,
            name: "Autumn launch",
          }),
          approvalControls(),
          toolUi([
            field("name", "Budget Name", "text", true),
            field("amount", "Amount", "keyvalue"),
            field("explicitly_shared", "Shared Budget", "boolean"),
            field("delivery_method", "Delivery Method", "text", true),
          ])
        )
      )
    )

    expect(html).toContain("UK account")
    expect(html).toContain("EU account")
    expect(html).toMatch(/£12\.50|GBP\s*12\.50/)
    expect(html).toMatch(/€12\.50|EUR\s*12\.50/)
    expect(html).toContain("estimated")
    expect(html).not.toContain("account currency")
    expect(html).not.toContain("Account Currencies")
  })

  it("renders created and failed budget evidence without inferring success", () => {
    const html = render(
      googleAdsCreateCampaignBudgetPresenter.render(
        props({
          ...activity("google_ads_create_campaign_budget", "completed", null),
          result: {
            results: [
              entry(
                {
                  amount: "12.5",
                  amount_micros: 12_500_000,
                  currency_code: "GBP",
                  delivery_method: "STANDARD",
                  explicitly_shared: true,
                  name: "Autumn launch",
                  outcome: "created",
                  period: "DAILY",
                  reference: budgetReference("55", "Autumn launch"),
                },
                "UK account",
                "1234567890"
              ),
              entry(
                {
                  amount: "12.5",
                  amount_micros: 12_500_000,
                  currency_code: "EUR",
                  delivery_method: "STANDARD",
                  error_code: "BUDGET_NAME_DUPLICATE",
                  explicitly_shared: true,
                  message: "A budget with this name already exists.",
                  name: "Autumn launch",
                  outcome: "failed",
                  period: "DAILY",
                  reference: null,
                },
                "EU account",
                "2234567890"
              ),
            ],
          },
        })
      )
    )

    expect(html).toContain("Created")
    expect(html).toContain("Failed")
    expect(html).toContain("Budget ID 55")
    expect(html).toContain("A budget with this name already exists.")
    expect(html).toContain("estimated per month")
  })

  it("blocks invalid total-budget combinations and decimal precision before approval", () => {
    const invalidCombination = render(
      googleAdsCreateCampaignBudgetPresenter.render(
        props(
          activity("google_ads_create_campaign_budget", "awaiting_approval", {
            _account_currencies: [{ label: "UK account", currency_code: "GBP" }],
            amount: { total_amount: "50" },
            delivery_method: "STANDARD",
            explicitly_shared: true,
            name: "Launch total",
          }),
          approvalControls()
        )
      )
    )
    const invalidPrecision = render(
      googleAdsCreateCampaignBudgetPresenter.render(
        props(
          activity("google_ads_create_campaign_budget", "awaiting_approval", {
            _account_currencies: [{ label: "UK account", currency_code: "GBP" }],
            amount: { daily_amount: "1.0000001" },
            delivery_method: "STANDARD",
            explicitly_shared: false,
            name: "Launch daily",
          }),
          approvalControls()
        )
      )
    )

    expect(invalidCombination).toContain("can&#x27;t be approved")
    expect(invalidPrecision).toContain("can&#x27;t be approved")
  })

  it("renders the trusted currency in the amount-update approval", () => {
    const liveBudget: Record<string, unknown> = budgetReference("55", "Autumn launch")
    delete liveBudget["entity_kind"]
    const html = render(
      googleAdsUpdateCampaignBudgetAmountsPresenter.render(
        props(
          activity("google_ads_update_campaign_budget_amounts", "awaiting_approval", {
            updates: [
              {
                amount: "15",
                budget: liveBudget,
              },
            ],
          }),
          approvalControls(),
          toolUi([field("updates", "Budget Amount Updates", "keyvalue")])
        )
      )
    )

    expect(html).toContain("Review each selected budget amount")
    expect(html).toContain("Autumn launch")
    expect(html).toContain("Current")
    expect(html).toMatch(/£10\.00|GBP\s*10/)
    expect(html).toContain("Proposed")
    expect(html).toMatch(/£15\.00|GBP\s*15/)
    expect(html).toContain("1 campaign")
  })

  it("rejects an explicitly wrong entity kind", () => {
    const html = render(
      googleAdsUpdateCampaignBudgetAmountsPresenter.render(
        props(
          activity("google_ads_update_campaign_budget_amounts", "awaiting_approval", {
            updates: [
              {
                amount: "15",
                budget: budgetReference("55", "Autumn launch", {
                  entity_kind: "google_ads_campaign",
                }),
              },
            ],
          }),
          approvalControls()
        )
      )
    )

    expect(html).toContain("can&#x27;t be approved")
  })

  it("blocks malformed spend approvals while keeping decline available", () => {
    const html = render(
      googleAdsUpdateCampaignBudgetAmountsPresenter.render(
        props(
          activity("google_ads_update_campaign_budget_amounts", "awaiting_approval", {
            updates: [{ amount: "15", budget: { budget_id: "55" } }],
          }),
          approvalControls(),
          toolUi([field("updates", "Budget Amount Updates", "keyvalue")])
        )
      )
    )

    expect(html).toContain("can&#x27;t be approved")
    expect(html).toContain("Decline this request")
    expect(html).toMatch(/<button[^>]*>Decline<\/button>/)
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Decline<\/button>/)
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
  })

  it("blocks amount updates when the current amount is unavailable", () => {
    const html = render(
      googleAdsUpdateCampaignBudgetAmountsPresenter.render(
        props(
          activity("google_ads_update_campaign_budget_amounts", "awaiting_approval", {
            updates: [
              {
                amount: "15",
                budget: budgetReference("55", "Autumn launch", { amount_micros: null }),
              },
            ],
          }),
          approvalControls()
        )
      )
    )

    expect(html).toContain("can&#x27;t be approved")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
  })

  it("keeps account-scoped budget identities distinct", () => {
    const html = render(
      googleAdsUpdateCampaignBudgetAmountsPresenter.render(
        props(
          activity("google_ads_update_campaign_budget_amounts", "awaiting_approval", {
            updates: [
              { amount: "15", budget: budgetReference("55", "UK budget") },
              {
                amount: "20",
                budget: budgetReference("55", "EU budget", { customer_id: "2234567890" }),
              },
            ],
          }),
          approvalControls(),
          toolUi([field("updates", "Budget Amount Updates", "keyvalue")])
        )
      )
    )

    expect(html).toContain("UK budget")
    expect(html).toContain("EU budget")
    expect(html).not.toContain("can&#x27;t be approved")
  })

  it("rejects unsafe numeric micros and formats exact string micros", () => {
    const unsafe = render(
      googleAdsRemoveCampaignBudgetsPresenter.render(
        props(
          activity("google_ads_remove_campaign_budgets", "awaiting_approval", {
            budgets: [
              budgetReference("70", "Unsafe", {
                amount_micros: Number.MAX_SAFE_INTEGER + 2,
                reference_count: 0,
              }),
            ],
          }),
          approvalControls()
        )
      )
    )
    const exact = render(
      googleAdsRemoveCampaignBudgetsPresenter.render(
        props(
          activity("google_ads_remove_campaign_budgets", "awaiting_approval", {
            budgets: [
              budgetReference("70", "Exact", {
                amount_micros: "9007199254740993000",
                reference_count: 0,
              }),
            ],
          }),
          approvalControls()
        )
      )
    )

    expect(unsafe).toContain("can&#x27;t be approved")
    expect(exact).toContain("GBP 9007199254740.993")
  })

  it("renders exact amount changes with proportional bars and separate outcomes", () => {
    const outcomes = ["updated", "already_set", "failed", "unverified"] as const
    const samples = Object.fromEntries(
      outcomes.map((outcome, index) => [
        outcome,
        [
          {
            campaign_label_count: index + 50,
            campaign_labels_truncated: false,
            error_code: outcome === "failed" ? "BUDGET_ERROR" : null,
            message: outcome === "failed" ? "Google Ads rejected this amount." : null,
            outcome,
            previous_amount: "10",
            previous_amount_micros: 10_000_000,
            reference: budgetReference(String(index + 1), `Budget ${String(index + 1)}`, {
              reference_count: index,
            }),
            requested_amount: index === 0 ? "15" : "10",
            requested_amount_micros: index === 0 ? 15_000_000 : 10_000_000,
          },
        ],
      ])
    )
    const html = render(
      googleAdsUpdateCampaignBudgetAmountsPresenter.render(
        props({
          ...activity("google_ads_update_campaign_budget_amounts", "completed", null),
          result: {
            results: [
              entry({
                campaign_labels_truncated: false,
                counts: { already_set: 1, failed: 1, unverified: 1, updated: 1 },
                samples,
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Before")
    expect(html).toContain("After")
    expect(html).toContain("+50% from the previous amount")
    expect(html).toContain("Already set")
    expect(html).toContain("Unverified")
    expect(html).toContain("Google Ads rejected this amount.")
    expect(html).toContain("0 campaigns")
    expect(html).not.toContain("50 campaigns")
    expect(html).toContain("4 rows")
    expect(html).toContain("Download Report CSV")
  })

  it("shows every campaign route before approval and after assignment", () => {
    const destination = budgetReference("90", "Shared growth budget", {
      explicitly_shared: true,
      reference_count: 2,
    })
    const approvalHtml = render(
      googleAdsAssignCampaignBudgetsPresenter.render(
        props(
          activity("google_ads_assign_campaign_budgets", "awaiting_approval", {
            _budget_routes: [
              {
                campaign: campaignReference("10", "Brand"),
                destination_budget: destination,
                previous_budget: budgetReference("50", "Brand budget"),
              },
              {
                campaign: campaignReference("20", "Shopping"),
                destination_budget: destination,
                previous_budget: destination,
              },
            ],
            campaigns: [campaignReference("10", "Brand"), campaignReference("20", "Shopping")],
            destination_budget: destination,
          }),
          approvalControls(),
          toolUi([
            field("destination_budget", "Destination Budget", "entity", true),
            field("campaigns", "Campaigns", "entity_list", true),
          ])
        )
      )
    )
    const resultHtml = render(
      googleAdsAssignCampaignBudgetsPresenter.render(
        props({
          ...activity("google_ads_assign_campaign_budgets", "completed", null),
          result: {
            results: [
              entry({
                counts: { already_set: 1, assigned: 1, failed: 0, unverified: 0 },
                destination_budget: { ...destination, reference_count: 3 },
                samples: {
                  already_set: [
                    assignmentSample("20", "Shopping", destination, destination, "already_set"),
                  ],
                  assigned: [
                    assignmentSample(
                      "10",
                      "Brand",
                      budgetReference("50", "Brand budget"),
                      destination,
                      "assigned"
                    ),
                  ],
                  failed: [],
                  unverified: [],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(approvalHtml).toContain("Brand")
    expect(approvalHtml).toContain("Shopping")
    expect(approvalHtml).toContain("Shared growth budget")
    expect(approvalHtml).toContain("Brand budget")
    expect(approvalHtml).toContain("→")
    expect(resultHtml).toContain("Brand budget")
    expect(resultHtml).toContain("Shared growth budget")
    expect(resultHtml).toContain(">Before<")
    expect(resultHtml).toContain(">After<")
    expect(resultHtml).not.toContain("→")
    expect(resultHtml).toContain("Already set")
    expect(resultHtml).toContain("Assigned")
  })

  it("makes permanent removal explicit and preserves unverified results", () => {
    const unused = budgetReference("70", "Legacy budget", { reference_count: 0 })
    const approvalHtml = render(
      googleAdsRemoveCampaignBudgetsPresenter.render(
        props(
          activity("google_ads_remove_campaign_budgets", "awaiting_approval", {
            budgets: [unused],
          }),
          approvalControls(),
          toolUi([field("budgets", "Unused Campaign Budgets", "entity_list", true)])
        )
      )
    )
    const resultHtml = render(
      googleAdsRemoveCampaignBudgetsPresenter.render(
        props({
          ...activity("google_ads_remove_campaign_budgets", "completed", null),
          result: {
            results: [
              entry({
                counts: { failed: 0, removed: 1, unverified: 1 },
                samples: {
                  failed: [],
                  removed: [removalSample(unused, "removed", "REMOVED")],
                  unverified: [
                    removalSample(budgetReference("71", "Uncertain budget"), "unverified", null),
                  ],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(approvalHtml).toContain("cannot be undone")
    expect(approvalHtml).toContain("zero linked campaigns")
    expect(approvalHtml).toContain("Legacy budget")
    expect(resultHtml).toContain("Removed")
    expect(resultHtml).toContain("Unverified")
    expect(resultHtml).toContain("Uncertain budget")
  })

  it.each([
    [googleAdsCreateCampaignBudgetPresenter, "google_ads_create_campaign_budget"],
    [googleAdsUpdateCampaignBudgetAmountsPresenter, "google_ads_update_campaign_budget_amounts"],
    [googleAdsAssignCampaignBudgetsPresenter, "google_ads_assign_campaign_budgets"],
    [googleAdsRemoveCampaignBudgetsPresenter, "google_ads_remove_campaign_budgets"],
  ])("contains malformed, unverified, denied, and loading states for %s", (presenter, name) => {
    const malformed = render(
      presenter.render(
        props({ ...activity(name, "completed", null), result: { results: [entry({ bad: true })] } })
      )
    )
    const unverified = render(
      presenter.render(
        props({
          ...activity(name, "completed", null),
          result: {
            results: [
              {
                ...entry(null),
                error_code: "unverified_mutation",
                error_message: "raw provider error",
                status: "error",
              },
            ],
          },
        })
      )
    )

    expect(malformed).toContain("couldn&#x27;t verify")
    expect(unverified).toContain("couldn&#x27;t verify whether Google Ads")
    expect(unverified).not.toContain("raw provider error")
    const denied = activity(name, "denied", null)
    denied.decisionReason = "The budget is too high."
    const deniedHtml = render(presenter.render(props(denied)))
    expect(deniedHtml).toContain("declined")
    expect(deniedHtml).toContain("Declined")
    expect(deniedHtml).toContain("The budget is too high.")
    expect(deniedHtml).not.toContain("Failed")
    expect(render(presenter.render(props(activity(name, "running", null))))).toContain("…")
  })
})

function activity(name: string, status: ToolActivity["status"], args: unknown): ToolActivity {
  return { args, id: `${name}:${status}`, kind: "approval", name, status }
}

function props(
  value: ToolActivity,
  approvalDecision?: Parameters<ToolRowPresenter["render"]>[0]["approvalDecision"],
  ui?: ToolUi
) {
  return {
    activity: value,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ...(ui ? { ui } : {}),
  }
}

function entry(data: unknown, displayName = "Client account", externalId = "1234567890") {
  return {
    data,
    display_name: displayName,
    error_message: null,
    external_id: externalId,
    provider_key: "google_ads",
    status: "success",
  }
}

function budgetReference(budgetId: string, label: string, overrides: Record<string, unknown> = {}) {
  return {
    amount_micros: 10_000_000,
    budget_id: budgetId,
    campaign_labels: [],
    currency_code: "GBP",
    delivery_method: "STANDARD",
    entity_kind: "google_ads_campaign_budget",
    explicitly_shared: false,
    customer_id: "1234567890",
    label,
    period: "DAILY",
    reference_count: 1,
    status: "ENABLED",
    total_amount_micros: null,
    version: 1,
    ...overrides,
  }
}

function campaignReference(campaignId: string, label: string) {
  return {
    campaign_id: campaignId,
    customer_id: "1234567890",
    entity_kind: "google_ads_campaign",
    label,
    version: 1,
  }
}

function assignmentSample(
  campaignId: string,
  campaignLabel: string,
  previousBudget: ReturnType<typeof budgetReference>,
  requestedBudget: ReturnType<typeof budgetReference>,
  outcome: "already_set" | "assigned"
) {
  return {
    campaign: campaignReference(campaignId, campaignLabel),
    error_code: null,
    external_ref: outcome === "assigned" ? `customers/123/campaigns/${campaignId}` : null,
    message: null,
    outcome,
    previous_budget: previousBudget,
    requested_budget: requestedBudget,
  }
}

function removalSample(
  reference: ReturnType<typeof budgetReference>,
  outcome: "removed" | "unverified",
  resultingStatus: string | null
) {
  return {
    error_code: null,
    external_ref:
      outcome === "removed" ? `customers/123/campaignBudgets/${reference.budget_id}` : null,
    message: outcome === "unverified" ? "Check Google Ads before retrying." : null,
    outcome,
    previous_status: "ENABLED",
    reference,
    resulting_status: resultingStatus,
  }
}

function approvalControls() {
  return {
    decision: { decision: "pending" as const, edits: {}, message: "" as const },
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}

function field(
  key: string,
  label: string,
  format: ToolUiField["format"],
  editable = false
): ToolUiField {
  return {
    editable,
    format,
    key,
    label,
    min_rows: 0,
    options: [],
    placeholder: "",
    secondary: false,
  }
}

function toolUi(argFields: ToolUiField[]): ToolUi {
  return {
    approval_prompt: "",
    approval_title: "",
    approve_label: "",
    arg_fields: argFields,
    completed_label: "",
    failed_label: "",
    icon: "google_ads",
    result_fields: [],
    running_label: "",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
