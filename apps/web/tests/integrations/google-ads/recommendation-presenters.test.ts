import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ToolApprovalDecisionCard } from "@/components/tool-ui/approval-card"
import type { ToolUi, ToolUiField } from "@/features/tools/types"
import type { ToolActivity } from "@/integrations/contract"
import { googleAdsApplyRecommendationsPresenter } from "@/integrations/google_ads/presenters/apply-recommendations"

describe("Google Ads recommendation presenters", () => {
  it("reviews edited apply selections and typed parameters through the shared approval controls", () => {
    const controls = approvalControls()
    controls.decision.edits = {
      parameters: [
        {
          recommendation_resource_name: recommendationName("2"),
          parameter_type: "setTargetRoas",
          target_roas: 3.5,
          campaign_budget_amount_micros: 2_500_000,
        },
      ],
      recommendations: [recommendationReference("2", "Set target ROAS", "SET_TARGET_ROAS")],
    }
    const fields = applyFields()
    const rendered = googleAdsApplyRecommendationsPresenter.render(
      props(
        {
          args: {
            recommendations: [
              recommendationReference("1", "Raise campaign budget", "CAMPAIGN_BUDGET"),
            ],
          },
          id: "apply-approval",
          kind: "approval",
          name: "google_ads_apply_recommendations",
          status: "awaiting_approval",
        },
        controls,
        toolUi(fields)
      )
    )

    expect(isValidElement(rendered)).toBe(true)
    if (isValidElement<{ controls: unknown; fields: ToolUiField[] }>(rendered)) {
      expect(rendered.type).toBe(ToolApprovalDecisionCard)
      expect(rendered.props.controls).toBe(controls)
      expect(rendered.props.fields).toBe(fields)
    }
    const html = render(rendered)
    expect(html).toContain("Set target ROAS")
    expect(html).not.toContain("Raise campaign budget")
  })

  it("blocks duplicate or unmatched apply parameter edits", () => {
    const controls = approvalControls()
    controls.decision.edits = {
      parameters: [
        {
          recommendation_resource_name: recommendationName("2"),
          parameter_type: "campaignBudget",
          new_budget_amount_micros: 2_500_000,
        },
      ],
    }
    const html = render(
      googleAdsApplyRecommendationsPresenter.render(
        props(
          {
            args: {
              recommendations: [
                recommendationReference("1", "Raise campaign budget", "CAMPAIGN_BUDGET"),
              ],
            },
            id: "apply-invalid-approval",
            kind: "approval",
            name: "google_ads_apply_recommendations",
            status: "awaiting_approval",
          },
          controls,
          toolUi(applyFields())
        )
      )
    )

    expect(html).toContain("match each custom parameter row")
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Apply<\/button>/)
  })

  it.each([
    { parameter_type: "campaignBudget", new_budget_amount_micros: 1_000_000 },
    {
      parameter_type: "keyword",
      ad_group: "customers/1234567890/adGroups/10",
      match_type: "PHRASE",
      cpc_bid_micros: 500_000,
    },
  ])("accepts the $parameter_type parameter variant", (parameter) => {
    const html = render(
      googleAdsApplyRecommendationsPresenter.render(
        props(
          {
            args: {
              parameters: [
                {
                  ...parameter,
                  recommendation_resource_name: recommendationName("1"),
                },
              ],
              recommendations: [
                recommendationReference("1", "Selected recommendation", "CAMPAIGN_BUDGET"),
              ],
            },
            id: `apply-${parameter.parameter_type}`,
            kind: "approval",
            name: "google_ads_apply_recommendations",
            status: "awaiting_approval",
          },
          approvalControls(),
          toolUi(applyFields())
        )
      )
    )

    expect(html).toContain("Approve &amp; Apply")
    expect(html).not.toContain("Choose valid recommendations")
  })

  it.each([
    { parameter_type: "campaignBudget", new_budget_amount_micros: 1.5 },
    { parameter_type: "keyword", ad_group: "  ", match_type: "EXACT" },
    { parameter_type: "setTargetRoas", target_roas: 1001 },
  ])("blocks invalid scalar values in $parameter_type", (parameter) => {
    const html = render(
      googleAdsApplyRecommendationsPresenter.render(
        props(
          {
            args: {
              parameters: [{ ...parameter, recommendation_resource_name: recommendationName("1") }],
              recommendations: [
                recommendationReference("1", "Selected recommendation", "CAMPAIGN_BUDGET"),
              ],
            },
            id: "apply-invalid-scalar",
            kind: "approval",
            name: "google_ads_apply_recommendations",
            status: "awaiting_approval",
          },
          approvalControls(),
          toolUi(applyFields())
        )
      )
    )
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Apply<\/button>/)
  })

  describe.each([["setTargetRoas", "target_roas", "campaign_budget_amount_micros"]])(
    "%s optional parameter presence",
    (parameterType, firstKey, secondKey) => {
      it.each([
        { first: 3, second: undefined },
        { first: undefined, second: undefined },
        { first: 3, second: 0 },
        { first: null, second: 3 },
      ])("validates approval and result values $first / $second", ({ first, second }) => {
        const parameters = {
          parameter_type: parameterType,
          recommendation_resource_name: recommendationName("1"),
          ...(first === undefined ? {} : { [firstKey]: first }),
          ...(second === undefined ? {} : { [secondKey]: second }),
        }
        const valid =
          [first, second].every((value) => value == null || value === 3) &&
          [first, second].some((value) => value === 3)
        const activity: ToolActivity = {
          id: "pair",
          kind: "approval",
          name: "google_ads_apply_recommendations",
          status: "awaiting_approval",
          args: {
            recommendations: [recommendationReference("1", "Selected", "SET_TARGET_ROAS")],
            parameters: [parameters],
          },
        }
        const approval = render(
          googleAdsApplyRecommendationsPresenter.render(props(activity, approvalControls()))
        )
        expect(/<button[^>]*disabled=""[^>]*>Approve &amp; Apply<\/button>/.test(approval)).toBe(
          !valid
        )
        const result = render(
          googleAdsApplyRecommendationsPresenter.render(
            props({
              ...activity,
              status: "completed",
              result: {
                results: [
                  entry({
                    recommendations: [
                      applyOutcome("1", "Selected", "SET_TARGET_ROAS", "applied", {
                        requested_parameters: parameters,
                      }),
                    ],
                  }),
                ],
              },
            })
          )
        )
        expect(result.includes("Download Report CSV")).toBe(valid)
      })
    }
  )

  it("renders every apply outcome with campaigns, parameters, and Google impact estimates", () => {
    const html = render(
      googleAdsApplyRecommendationsPresenter.render(
        props({
          args: {
            recommendations: [
              recommendationReference("1", "Raise campaign budget", "CAMPAIGN_BUDGET"),
              recommendationReference("2", "Add keyword", "KEYWORD"),
              recommendationReference("3", "Set target CPA", "SET_TARGET_CPA"),
            ],
          },
          id: "apply-result",
          kind: "result",
          name: "google_ads_apply_recommendations",
          result: {
            results: [
              entry({
                recommendations: [
                  applyOutcome("1", "Raise campaign budget", "CAMPAIGN_BUDGET", "applied", {
                    impact: {
                      base_metrics: {
                        clicks: 100,
                        conversions: 8,
                        cost_micros: 50_000_000,
                        impressions: 1_000,
                      },
                      potential_metrics: {
                        clicks: 125,
                        conversions: 10,
                        cost_micros: 60_000_000,
                        impressions: 1_250,
                      },
                    },
                    requested_parameters: {
                      recommendation_resource_name: recommendationName("1"),
                      parameter_type: "campaignBudget",
                      new_budget_amount_micros: 2_500_000,
                    },
                  }),
                  applyOutcome("2", "Add keyword", "KEYWORD", "failed", {
                    error_code: "POLICY_FINDING",
                    message: "Google Ads rejected this keyword.",
                  }),
                  applyOutcome("3", "Set target CPA", "SET_TARGET_CPA", "unverified", {
                    error_code: "REQUEST_TIMEOUT",
                    message: "The provider response was interrupted.",
                  }),
                ],
              }),
            ],
          },
          status: "completed",
        })
      )
    )

    expect(html).toContain("Clicks: 100 → 125")
    expect(html).toContain("Download Report CSV")
  })

  it("isolates malformed and account-level unverified apply results", () => {
    const malformed = render(
      googleAdsApplyRecommendationsPresenter.render(
        props({
          id: "apply-malformed",
          kind: "result",
          name: "google_ads_apply_recommendations",
          result: { results: [entry({ recommendations: [{ outcome: "applied" }] })] },
          status: "completed",
        })
      )
    )
    const unverified = render(
      googleAdsApplyRecommendationsPresenter.render(
        props({
          id: "apply-unverified",
          kind: "result",
          name: "google_ads_apply_recommendations",
          result: {
            results: [
              {
                ...entry(null),
                error_code: "unverified_mutation",
                error_message: "transport error",
                status: "error",
              },
            ],
          },
          status: "completed",
        })
      )
    )

    expect(malformed).toContain("couldn&#x27;t confirm the recommendations outcome")
    expect(unverified).toContain("couldn&#x27;t verify whether Google Ads applied")
    expect(unverified).not.toContain("transport error")
  })
})

function props(
  activity: ToolActivity,
  approvalDecision?: Parameters<
    typeof googleAdsApplyRecommendationsPresenter.render
  >[0]["approvalDecision"],
  ui?: ToolUi
) {
  return {
    activity,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ...(ui ? { ui } : {}),
  }
}

function recommendationName(id: string): string {
  return `customers/1234567890/recommendations/${id}`
}

function recommendationReference(id: string, label: string, recommendationType: string) {
  return {
    customer_id: "1234567890",
    entity_kind: "google_ads_recommendation",
    label,
    recommendation_type: recommendationType,
    resource_name: recommendationName(id),
    version: 1,
  }
}

function applyOutcome(
  id: string,
  label: string,
  recommendationType: string,
  outcome: "applied" | "failed" | "unverified",
  overrides: Record<string, unknown> = {}
) {
  return {
    affected_campaigns: ["Summer campaign"],
    error_code: null,
    external_ref: outcome === "applied" ? recommendationName(id) : null,
    impact: null,
    message: null,
    outcome,
    recommendation_label: label,
    recommendation_resource_name: recommendationName(id),
    recommendation_type: recommendationType,
    requested_parameters: null,
    ...overrides,
  }
}

function entry(data: unknown) {
  return {
    data,
    display_name: "Client account",
    error_message: null,
    external_id: "1234567890",
    provider_key: "google_ads",
    status: "success",
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

function applyFields(): ToolUiField[] {
  return [
    field("recommendations", "Recommendations", "entity_list", true),
    field("parameters", "Custom parameters", "list", true),
  ]
}

function field(
  key: string,
  label: string,
  format: ToolUiField["format"],
  editable: boolean
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

function render(node: ReactNode): string {
  return renderToStaticMarkup(createElement("div", null, node))
}
