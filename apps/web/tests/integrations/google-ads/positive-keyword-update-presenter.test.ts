import { createElement, type ComponentProps, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity, ToolRowPresenter } from "@/integrations/contract"
import type * as SelectModule from "@/components/ui/select"
import type { ToolUi } from "@/features/tools/types"
import { replacePositiveKeywordPatch } from "@/integrations/google_ads/lib/positive-keyword-update"
import { googleAdsUpdatePositiveKeywordsPresenter } from "@/integrations/google_ads/presenters/update-positive-keywords"

const statusEdits = vi.hoisted(() => [] as ((value: string) => void)[])

vi.mock("@/components/ui/select", async (importOriginal) => {
  const original = await importOriginal<typeof SelectModule>()
  return {
    ...original,
    Select: (props: ComponentProps<typeof original.Select>) => {
      if (props.onValueChange) statusEdits.push(props.onValueChange as (value: string) => void)
      return createElement(original.Select, props)
    },
  }
})

describe("Google Ads positive keyword update presenter", () => {
  it.each([false, true])("preserves status edits and the submitting lock (%s)", (submitting) => {
    statusEdits.length = 0
    const controls = { ...approvalControls(), submitting }
    render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [keyword("PAUSED"), { ...keyword("PAUSED"), criterion_id: "91" }],
            patches: [{ status: "ENABLED", cpc_bid: "2.50" }, { status: "ENABLED" }],
          }),
          controls
        )
      )
    )
    expect(statusEdits).toHaveLength(2)
    statusEdits[1]?.("PAUSED")
    if (submitting) {
      expect(controls.onDecisionChange).not.toHaveBeenCalled()
    } else {
      expect(controls.onDecisionChange).toHaveBeenCalledWith({
        decision: "pending",
        message: "",
        edits: { patches: [{ status: "ENABLED", cpc_bid: "2.50" }, { status: "PAUSED" }] },
      })
    }
  })

  it("shows selected keyword labels as failure chips", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("failed", {
            keywords: [keyword("PAUSED")],
            patches: [{ status: "ENABLED" }],
            _account_currencies: [
              { customer_id: "1234567890", currency_code: "GBP", label: "Shop" },
            ],
          })
        )
      )
    )
    expect(html).toMatch(/data-slot="badge"[^>]*>running shoes/)
  })

  it("separates confirmed state from requested state without arrows", () => {
    const before = state("PAUSED", "1.25", ["https://example.com/old"])
    const requested = state("ENABLED", null, [])
    const html = renderResult({ updated: [resultRow("updated", before, requested)] })
    expect(html).toContain(">Before<")
    expect(html).toContain(">After<")
    expect(html).toContain(">Requested<")
    expect(html).not.toContain("→")
    const failed = renderResult({ failed: [resultRow("failed", before, requested)] })
    expect(
      (failed.match(/<td[\s\S]*?<\/td>/g) ?? []).map((cell) => cell.replace(/<[^>]*>/g, ""))
    ).toContain("Unverified")
  })

  it.each(["utm_source=my-campaign", "MiXeD_{lpurl}", "ENABLED", "PAUSED"])(
    "preserves the literal suffix %s in approval comparisons and exported result cells",
    (suffix) => {
      const approval = render(
        googleAdsUpdatePositiveKeywordsPresenter.render(
          props(
            activity("awaiting_approval", {
              keywords: [keyword("PAUSED")],
              patches: [{ final_url_suffix: suffix }],
            }),
            approvalControls()
          )
        )
      )
      expect(approval).toContain(`>${suffix}<`)
      const before = state("PAUSED", "1.25", ["https://example.com/old"])
      const row = {
        ...resultRow("updated", before, { ...before, final_url_suffix: suffix }),
        keyword: { ...keyword("PAUSED"), final_url_suffix: suffix },
        requested_fields: ["final_url_suffix"],
        update_mask: "finalUrlSuffix",
      }
      const html = renderResult({ updated: [row] })
      expect(html).toContain(`Final URL suffix: ${suffix}`)
      expect(html).toContain("Download Report CSV")
    }
  )

  it("rejects contradictory per-outcome counts even when their total matches", () => {
    const row = resultRow(
      "updated",
      state("PAUSED", "1.25", ["https://example.com/old"]),
      state("ENABLED", null, [])
    )
    expect(
      renderResult({ updated: [row] }, { updated: 0, failed: 1, already_set: 0, unverified: 0 })
    ).not.toContain("Download Report CSV")
  })

  it("rejects duplicate identities within and across outcome collections", () => {
    const before = state("PAUSED", "1.25", ["https://example.com/old"])
    const requested = state("ENABLED", null, [])
    const updated = resultRow("updated", before, requested)
    const failed = resultRow("failed", before, requested)
    expect(renderResult({ updated: [updated, updated] })).not.toContain("Download Report CSV")
    expect(renderResult({ updated: [updated], failed: [failed] })).not.toContain(
      "Download Report CSV"
    )
  })

  it("accepts matching criterion IDs in different ad groups", () => {
    const row = resultRow(
      "updated",
      state("PAUSED", "1.25", ["https://example.com/old"]),
      state("ENABLED", null, [])
    )
    expect(
      renderResult({ updated: [row, { ...row, keyword: { ...row.keyword, ad_group_id: "21" } }] })
    ).toContain("Download Report CSV")
  })
  it("keeps fixed keyword rows compact until advanced fields are opened", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [keyword("ENABLED")],
            patches: [{ status: "PAUSED" }],
          }),
          approvalControls()
        )
      )
    )

    expect(html).toContain("Status")
    expect(html).toContain("More fields")
    expect(html).toContain("CPC bid")
    expect(html).not.toContain("Final URLs")
    expect(html).not.toContain("Add Row")
    expect(html).not.toContain("Remove row")
  })

  it("shows exact guarded before and requested values for every requested field", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [keyword("PAUSED")],
            patches: [
              {
                cpc_bid: "",
                final_urls: [],
                status: "ENABLED",
                tracking_url_template: "",
              },
            ],
          }),
          approvalControls()
        )
      )
    )

    expect(html).toContain("Proposed keyword changes")
    expect(html).toContain("running shoes")
    expect(html).toContain("Search · Shoes")
    expect(html).toContain("CPC bid")
    expect(html).toContain("1.25")
    expect(html).toContain("Cleared")
    expect(html).not.toContain("Changing match type requires two separate approvals")
    expect(html).toContain("Less fields")
    expect(html).toContain("UK account")
    expect(html).toContain("GBP")
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
  })

  it("renders nullable bid adjustments as row-specific number inputs", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [keyword("PAUSED")],
            patches: [{ bid_modifier: "" }],
          }),
          approvalControls()
        )
      )
    )

    expect(html).toContain(
      'aria-label="Bid adjustment for running shoes, Exact, in Search · Shoes, account 1234567890"'
    )
    expect(html).toMatch(
      /<input[^>]*type="number"[^>]*aria-label="Bid adjustment for running shoes[^>]*value=""/
    )
    expect(html).not.toContain("Changed. ")
    expect(html).not.toContain("Cleared")
  })

  it("locks every fixed-row editor while approval is submitting", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [keyword("PAUSED")],
            patches: [{ status: "ENABLED" }],
          }),
          { ...approvalControls(), submitting: true }
        )
      )
    )

    expect(html).not.toContain('role="checkbox"')
    expect(html).toMatch(/<input[^>]*disabled=""[^>]*aria-label="CPC bid for running shoes/)
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*aria-label="Status for running shoes/)
  })

  it("paginates the fixed approval rows without discarding edits", () => {
    const keywords = Array.from({ length: 30 }, (_value, index) => keywordAt(index))
    const patches = keywords.map(() => ({ status: "PAUSED" }))
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(activity("awaiting_approval", { keywords, patches }), approvalControls())
      )
    )

    expect(html).toContain("1 of 2")
    expect(html).toContain("keyword 024")
    expect(html).not.toContain("keyword 025")
    expect(html).not.toContain("Add Row")
    expect(html).not.toContain("Remove row")
  })

  it("replaces one positional patch without changing any other keyword association", () => {
    const patches = [{ status: "PAUSED" as const }, { cpc_bid: "2.00" }]
    const changed = replacePositiveKeywordPatch(patches, 1, { cpc_bid: null })

    expect(changed).toEqual([{ status: "PAUSED" }, { cpc_bid: null }])
    expect(changed).toHaveLength(patches.length)
    expect(changed[0]).toBe(patches[0])
    expect(patches[1]).toEqual({ cpc_bid: "2.00" })
  })

  it("rejects an empty patch and mismatched positional rows", () => {
    const emptyPatch = googleAdsUpdatePositiveKeywordsPresenter.render(
      props(
        activity("awaiting_approval", {
          keywords: [keyword("PAUSED")],
          patches: [{}],
        }),
        approvalControls()
      )
    )
    const missingPatch = googleAdsUpdatePositiveKeywordsPresenter.render(
      props(
        activity("awaiting_approval", {
          keywords: [keyword("PAUSED")],
          patches: [],
        }),
        approvalControls()
      )
    )

    expect(render(emptyPatch)).toContain("can&#x27;t be approved")
    expect(render(missingPatch)).toContain("can&#x27;t be approved")
  })

  it.each([{}, { cpc_bid: "2." }, { final_urls: ["not-a-url"] }, { bid_modifier: 20 }])(
    "keeps recoverable invalid draft %j mounted while blocking approval",
    (patch) => {
      const controls = {
        ...approvalControls(),
        decision: {
          decision: "pending" as const,
          edits: { patches: [patch] },
          message: "" as const,
        },
      }
      const html = render(
        googleAdsUpdatePositiveKeywordsPresenter.render(
          props(
            activity("awaiting_approval", {
              keywords: [keyword("PAUSED")],
              patches: [{ status: "ENABLED" }],
            }),
            controls
          )
        )
      )
      expect(html).toContain("Proposed keyword changes")
      expect(html).toContain("Provide one valid change row")
      expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
      if ("cpc_bid" in patch) expect(html).toContain('value="2."')
      if ("final_urls" in patch) expect(html).toContain("not-a-url")
    }
  )

  it("distinguishes match variants and account scopes in accessible control names", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [
              keyword("PAUSED"),
              { ...keyword("PAUSED"), criterion_id: "91", match_type: "PHRASE" },
            ],
            patches: [{ status: "ENABLED" }, { status: "ENABLED" }],
          }),
          approvalControls()
        )
      )
    )
    expect(html).toContain("Status for running shoes, Exact, in Search · Shoes, account 1234567890")
    expect(html).toContain(
      "Status for running shoes, Phrase, in Search · Shoes, account 1234567890"
    )
    expect(html).toContain(">Current<")
    expect(html).toContain(">Proposed<")
  })

  it("allows destination inheritance for independent URL settings", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props(
          activity("awaiting_approval", {
            keywords: [{ ...keyword("PAUSED"), final_urls: [], final_url_suffix: "src=ads" }],
            patches: [{ status: "ENABLED" }],
          }),
          approvalControls()
        )
      )
    )
    expect(html).toContain("Proposed keyword changes")
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve &amp; Update<\/button>/)
  })

  it("renders exact before and requested settings with partial outcomes", () => {
    const before = state("PAUSED", "1.25", ["https://example.com/old"])
    const after = state("ENABLED", null, [])
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                currency_code: "GBP",
                counts: { already_set: 0, failed: 1, unverified: 0, updated: 1 },
                samples: {
                  already_set: [],
                  failed: [
                    {
                      ...resultRow("failed", before, after),
                      keyword: { ...keyword("PAUSED"), criterion_id: "91" },
                      error_code: "CANNOT_MODIFY",
                      message: "Criterion cannot be changed.",
                    },
                  ],
                  unverified: [],
                  updated: [resultRow("updated", before, after)],
                },
                samples_truncated: false,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("Update Keywords")
    expect(html).toContain("Criterion cannot be changed.")
    expect(html).toContain("Status: Paused")
    expect(html).toContain("Status: Enabled")
    expect(html).toContain("CPC bid: 1.25 GBP")
    expect(html).toContain("Download Report CSV")
  })

  it("keeps denied, loading, malformed, and unverified states distinct", () => {
    const denied = activity("denied", {
      keywords: [keyword("PAUSED")],
      patches: [{ status: "ENABLED" }],
    })
    denied.decisionReason = "Keep this keyword paused."
    const deniedHtml = render(googleAdsUpdatePositiveKeywordsPresenter.render(props(denied)))
    const loadingHtml = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(props(activity("running", null)))
    )
    const malformedHtml = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props({ ...activity("completed", null), result: { results: [entry({ bad: true })] } })
      )
    )
    const unverifiedHtml = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
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
    expect(loadingHtml).toContain("Updating Google Ads keywords…")
    expect(malformedHtml).toContain("couldn&#x27;t verify")
    expect(unverifiedHtml).toContain("couldn&#x27;t verify whether Google Ads applied")
    expect(unverifiedHtml).not.toContain("provider transport detail")
  })

  it("rejects a result that omits accepted rows behind sampling", () => {
    const html = render(
      googleAdsUpdatePositiveKeywordsPresenter.render(
        props({
          ...activity("completed", null),
          result: {
            results: [
              entry({
                currency_code: "GBP",
                counts: { already_set: 0, failed: 0, unverified: 0, updated: 2 },
                samples: {
                  already_set: [],
                  failed: [],
                  unverified: [],
                  updated: [
                    resultRow(
                      "updated",
                      state("PAUSED", "1.25", ["https://example.com/old"]),
                      state("ENABLED", null, [])
                    ),
                  ],
                },
                samples_truncated: true,
              }),
            ],
          },
        })
      )
    )

    expect(html).toContain("couldn&#x27;t verify")
    expect(html).not.toContain("representative sample")
  })
})

function renderResult(samples: Record<string, unknown[]>, counts?: Record<string, number>) {
  const collections = { already_set: [], failed: [], unverified: [], updated: [], ...samples }
  return render(
    googleAdsUpdatePositiveKeywordsPresenter.render(
      props({
        ...activity("completed", null),
        result: {
          results: [
            entry({
              currency_code: "GBP",
              samples: collections,
              samples_truncated: false,
              counts:
                counts ??
                Object.fromEntries(
                  Object.entries(collections).map(([key, rows]) => [key, rows.length])
                ),
            }),
          ],
        },
      })
    )
  )
}

function activity(status: ToolActivity["status"], args: unknown): ToolActivity {
  const projectedArgs =
    status === "awaiting_approval" && args && typeof args === "object" && !Array.isArray(args)
      ? {
          ...args,
          _account_currencies: [
            { currency_code: "GBP", customer_id: "1234567890", label: "UK account" },
          ],
        }
      : args
  return {
    args: projectedArgs,
    id: `google_ads_update_keywords:${status}`,
    kind: "approval",
    name: "google_ads_update_keywords",
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
    ui: keywordUpdateUi(),
  }
}

function keyword(status: "ENABLED" | "PAUSED") {
  return {
    ad_group_id: "20",
    bid_modifier: null,
    campaign_id: "10",
    cpc_bid_micros: "1250000",
    criterion_id: "90",
    customer_id: "1234567890",
    entity_kind: "google_ads_keyword",
    final_mobile_urls: [],
    final_url_suffix: null,
    final_urls: ["https://example.com/old"],
    label: "running shoes",
    match_type: "EXACT",
    scope_label: "Search · Shoes",
    status,
    text: "running shoes",
    tracking_url_template: null,
    url_custom_parameters: [],
    version: 1,
  }
}

function keywordAt(index: number) {
  const text = `keyword ${String(index).padStart(3, "0")}`
  return {
    ...keyword("ENABLED"),
    criterion_id: String(index + 1),
    label: text,
    text,
  }
}

function state(status: "ENABLED" | "PAUSED", cpcBid: string | null, finalUrls: string[]) {
  return {
    bid_modifier: null,
    cpc_bid: cpcBid,
    final_mobile_urls: [],
    final_url_suffix: null,
    final_urls: finalUrls,
    status,
    tracking_url_template: null,
    url_custom_parameters: [],
  }
}

function resultRow(outcome: "failed" | "updated", before: unknown, requested: unknown) {
  return {
    before,
    error_code: null,
    external_ref: null,
    keyword: {
      ...keyword(outcome === "updated" ? "ENABLED" : "PAUSED"),
      cpc_bid_micros: outcome === "updated" ? null : "1250000",
      final_urls: outcome === "updated" ? [] : ["https://example.com/old"],
    },
    message: null,
    outcome,
    requested,
    requested_fields: ["status", "cpc_bid", "final_urls"],
    update_mask: "status,cpcBidMicros,finalUrls",
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

function keywordUpdateUi(): ToolUi {
  return {
    approval_prompt: "Review",
    approval_title: "Update Keywords",
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
        key: "patches",
        label: "Keyword Changes",
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
            required: false,
          },
          {
            key: "cpc_bid",
            label: "CPC bid",
            options: [],
            placeholder: "",
            required: false,
            secondary: true,
          },
          {
            key: "final_urls",
            label: "Final URLs",
            options: [],
            placeholder: "",
            required: false,
            secondary: true,
            format: "list",
          },
          {
            key: "tracking_url_template",
            label: "Tracking template",
            options: [],
            placeholder: "",
            required: false,
            secondary: true,
          },
        ],
      },
    ],
    completed_label: "Updated Keywords",
    failed_label: "Couldn't Update Keywords",
    icon: "google_ads",
    result_fields: [],
    running_label: "Updating Keywords",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, node))
}
