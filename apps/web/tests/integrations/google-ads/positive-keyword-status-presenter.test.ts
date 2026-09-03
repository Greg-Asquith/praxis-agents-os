import { createElement, isValidElement, type ReactElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { EditedValues } from "@/components/tool-ui/edited-values"
import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import type { ToolUi } from "@/features/tools/types"
import { googleAdsUpdatePositiveKeywordStatusPresenter } from "@/integrations/google_ads/presenters/update-positive-keyword-status"

describe("Google Ads positive keyword status presenter", () => {
  it("shows each approval transition and reflects a status edit", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordStatusPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [keyword("ENABLED")],
            statuses: [{ status: "ENABLED" }],
          }),
          approvalControls({ statuses: [{ status: "PAUSED" }] })
        )
      )
    )

    expect(html).toContain("Proposed keyword status changes")
    expect(html).toContain("running shoes")
    expect(html).toContain("Search · Shoes")
    expect(html).toContain("Enabled before, Paused after")
    expect(html).toContain("Requested status for running shoes in Search · Shoes")
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
  })

  it("applies custom status edits through the approval decision", () => {
    const controls = approvalControls()
    const node = googleAdsUpdatePositiveKeywordStatusPresenter.render(
      props(
        activity("awaiting_approval", {
          keywords: [keyword("ENABLED")],
          statuses: [{ status: "ENABLED" }],
        }),
        controls
      )
    )
    const editor = findElement(
      node,
      (element) => typeof element.props["onValueChange"] === "function"
    )

    expect(editor).not.toBeNull()
    const onValueChange = editor?.props["onValueChange"] as ((value: string) => void) | undefined
    if (typeof onValueChange === "function") onValueChange("PAUSED")
    expect(controls.onDecisionChange).toHaveBeenCalledWith({
      decision: "pending",
      edits: { statuses: [{ status: "PAUSED" }] },
      message: "",
    })
  })

  it("locks the custom status editor while approval is submitting", () => {
    const controls = {
      ...approvalControls(),
      decision: { decision: "approved" as const, edits: {}, message: "" as const },
      submitting: true,
    }
    const node = googleAdsUpdatePositiveKeywordStatusPresenter.render(
      props(
        activity("awaiting_approval", {
          keywords: [keyword("ENABLED")],
          statuses: [{ status: "PAUSED" }],
        }),
        controls
      )
    )
    const editor = findElement(
      node,
      (element) => typeof element.props["onValueChange"] === "function"
    )

    expect(editor?.props["disabled"]).toBe(true)
    const onValueChange = editor?.props["onValueChange"] as ((value: string) => void) | undefined
    if (typeof onValueChange === "function") onValueChange("ENABLED")
    expect(controls.onDecisionChange).not.toHaveBeenCalled()
  })

  it("includes keyword scope in repeated editor names", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordStatusPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [
              keyword("ENABLED"),
              { ...keyword("PAUSED"), ad_group_id: "30", scope_label: "Search · Boots" },
            ],
            statuses: [{ status: "PAUSED" }, { status: "ENABLED" }],
          }),
          approvalControls()
        )
      )
    )

    expect(html).toContain("Requested status for running shoes in Search · Shoes")
    expect(html).toContain("Requested status for running shoes in Search · Boots")
  })

  it("renders exact before and after states with partial outcomes", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordStatusPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                counts: { already_set: 1, failed: 1, unverified: 0, updated: 1 },
                samples: {
                  already_set: [resultRow("already_set", "ENABLED", "ENABLED")],
                  failed: [
                    {
                      ...resultRow("failed", "PAUSED", "ENABLED"),
                      error_code: "CANNOT_MODIFY",
                      message: "Criterion cannot be changed.",
                    },
                  ],
                  unverified: [],
                  updated: [resultRow("updated", "PAUSED", "ENABLED")],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Update Keyword Status")
    expect(html).toContain("Already set")
    expect(html).toContain("Criterion cannot be changed.")
    expect(html).toContain("Paused")
    expect(html).toContain("Enabled")
    expect(html).toContain("Download Report CSV")
  })

  it("keeps loading, denied, malformed, and unverified states distinct", () => {
    const denied = activity("denied", {
      keywords: [keyword("PAUSED")],
      statuses: [{ status: "ENABLED" }],
    })
    denied.decisionReason = "Keep these keywords paused."
    const deniedHtml = render(googleAdsUpdatePositiveKeywordStatusPresenter.render(props(denied)))
    const loadingHtml = render(
      googleAdsUpdatePositiveKeywordStatusPresenter.render(props(activity("running", null)))
    )
    const malformedHtml = render(
      googleAdsUpdatePositiveKeywordStatusPresenter.render(
        props({ ...activity("completed", null), result: { results: [entry({ bad: true })] } })
      )
    )
    const unverifiedHtml = render(
      googleAdsUpdatePositiveKeywordStatusPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              {
                ...entry(null),
                error_code: "unverified_mutation",
                error_message: "provider transport detail",
                status: "error",
              },
            ],
          },
        })
      )
    )

    expect(deniedHtml).toContain("declined")
    expect(deniedHtml).toContain("Keep these keywords paused.")
    expect(loadingHtml).toContain("Updating Google Ads keyword status…")
    expect(malformedHtml).toContain("couldn&#x27;t verify")
    expect(unverifiedHtml).toContain("couldn&#x27;t verify whether Google Ads applied")
    expect(unverifiedHtml).not.toContain("provider transport detail")
  })
})

function activity(status: ToolActivity["status"], args: unknown): ToolActivity {
  return {
    args,
    id: `google_ads_update_keyword_status:${status}`,
    kind: "approval",
    name: "google_ads_update_keyword_status",
    status,
  }
}

function props(
  value: ToolActivity,
  approvalDecision?: Parameters<ToolRowPresenter["render"]>[0]["approvalDecision"]
) {
  return {
    activity: value,
    ...(approvalDecision ? { approvalDecision } : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
    ui: keywordStatusUi(),
  }
}

function keyword(status: "ENABLED" | "PAUSED") {
  return {
    ad_group_id: "20",
    campaign_id: "10",
    criterion_id: "90",
    customer_id: "1234567890",
    entity_kind: "google_ads_keyword",
    label: "running shoes",
    match_type: "EXACT",
    scope_label: "Search · Shoes",
    status,
    text: "running shoes",
    version: 1,
  }
}

function resultRow(
  outcome: "already_set" | "failed" | "unverified" | "updated",
  previous: "ENABLED" | "PAUSED",
  requested: "ENABLED" | "PAUSED"
) {
  return {
    error_code: null,
    external_ref: null,
    keyword: keyword(outcome === "updated" || outcome === "already_set" ? requested : previous),
    message: null,
    outcome,
    previous_status: previous,
    requested_status: requested,
  }
}

function entry(data: unknown) {
  return {
    data,
    display_name: "UK account",
    error_message: null,
    external_id: "1234567890",
    provider_key: "google_ads",
    status: "success",
  }
}

function approvalControls(edits: EditedValues = {}) {
  return {
    decision: { decision: "pending" as const, edits, message: "" as const },
    error: null,
    onDecisionChange: vi.fn(),
    onRetry: vi.fn(),
    pendingCount: 1,
    submitting: false,
  }
}

function keywordStatusUi(): ToolUi {
  return {
    approval_prompt: "Review",
    approval_title: "Update Keyword Status",
    approve_label: "Approve & Update",
    arg_fields: [
      {
        editable: false,
        entity_kind: "google_ads_keyword",
        format: "entity_list",
        key: "keywords",
        label: "Keywords",
        min_rows: 0,
        options: [],
        placeholder: "",
        secondary: false,
      },
      {
        editable: true,
        format: "records",
        key: "statuses",
        label: "Keyword Statuses",
        min_rows: 1,
        options: [],
        placeholder: "",
        secondary: false,
        columns: [
          {
            key: "status",
            label: "Status",
            options: ["ENABLED", "PAUSED"],
            placeholder: "",
            required: true,
          },
        ],
      },
    ],
    completed_label: "Updated Keyword Status",
    failed_label: "Couldn't Update Keyword Status",
    icon: "google_ads",
    result_fields: [],
    running_label: "Updating Keyword Status",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}

function findElement(
  node: ReactNode,
  predicate: (element: ReactElement<Record<string, unknown>>) => boolean
): ReactElement<Record<string, unknown>> | null {
  if (Array.isArray(node)) {
    for (const child of node as ReactNode[]) {
      const match = findElement(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!isValidElement<Record<string, unknown>>(node)) return null
  if (predicate(node)) return node
  return findElement(node.props["children"] as ReactNode, predicate)
}
