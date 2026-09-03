// apps/web/tests/integrations/google-search-console/write-approvals.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolUi } from "@/features/tools/types"
import { submitSitemapPresenter } from "@/integrations/google_search_console/presenters/submit-sitemap"

const UI: ToolUi = {
  icon: "google_search_console",
  running_label: "Submitting Search Console Sitemaps",
  completed_label: "Submitted Search Console Sitemaps",
  failed_label: "Couldn't Submit Search Console Sitemaps",
  approval_title: "Submit Sitemaps to Google Search Console",
  approval_prompt:
    "The agent wants Google to re-process these sitemaps. Google decides when and whether to crawl the URLs they list.",
  approve_label: "Approve & Submit",
  arg_fields: [
    {
      key: "sitemap_urls",
      label: "Sitemap URLs",
      min_rows: 0,
      format: "list",
      editable: true,
      placeholder: "",
      options: [],
      secondary: false,
    },
  ],
  result_fields: [
    {
      key: "results",
      label: "Sites",
      min_rows: 0,
      format: "list",
      editable: false,
      placeholder: "",
      options: [],
      secondary: false,
    },
  ],
}

const ARGS = {
  sitemap_urls: ["https://example.com/one.xml", "https://example.com/two.xml"],
  _sitemap_submission_status: [
    {
      sitemap_url: "https://example.com/one.xml",
      site_url: "https://example.com/",
      previously_submitted: true,
    },
    {
      sitemap_url: "https://example.com/two.xml",
      site_url: "https://example.com/",
      previously_submitted: false,
    },
  ],
  _sitemap_writable_sites: ["https://example.com/", "https://other.example/"],
}

describe("Search Console sitemap write presenter", () => {
  it("shows editable approval details and distinguishes add from resubmit", () => {
    const html = renderPresenter(activity("awaiting_approval", ARGS), pendingControls())

    expect(html).toContain("Submit Sitemaps to Google Search Console")
    expect(html).toContain("Google decides when and whether to crawl")
    expect(html).toContain("Resubmit")
    expect(html).toContain("Add")
    expect(html).toContain("Remove https://example.com/one.xml")
    expect(html).toContain("Approve &amp; Submit")
  })

  it("rejects an edited URL outside the selected writable sites", () => {
    const html = renderPresenter(
      activity("awaiting_approval", ARGS),
      controls({
        decision: "pending",
        edits: { sitemap_urls: ["https://other.example.net/sitemap.xml"] },
        message: "",
      })
    )

    expect(html).toContain("must belong to one of the selected writable Search Console sites")
    expect(html).not.toContain("https://example.com/one.xml</span>")
  })

  it("accepts an edited URL on another selected writable site", () => {
    const html = renderPresenter(
      activity("awaiting_approval", ARGS),
      controls({
        decision: "pending",
        edits: { sitemap_urls: ["https://other.example/sitemap.xml"] },
        message: "",
      })
    )

    expect(html).toContain("https://other.example/sitemap.xml")
    expect(html).not.toContain("must belong to one of the selected writable Search Console sites")
  })

  it("keeps declined, failed, and unverified outcomes explicit", () => {
    const denied = activity("denied", ARGS)
    denied.decisionReason = "Wait for the content deployment."
    const deniedHtml = renderPresenter(denied)
    expect(deniedHtml).toContain("This sitemap submission was declined. Nothing was submitted.")
    expect(deniedHtml).toContain("Wait for the content deployment.")
    expect(deniedHtml).toContain("Declined")

    const failedHtml = renderPresenter(activity("failed", ARGS))
    expect(failedHtml).toContain("No sitemap submission was confirmed")

    const unverifiedHtml = renderPresenter(
      resultActivity({
        results: [
          entry(
            {
              sitemaps: [submissionRow({ outcome: "unverified" })],
              submitted_count: 0,
              failed_count: 0,
            },
            {
              status: "error",
              error_code: "unverified_mutation",
              error_message: "The provider mutation outcome could not be verified exactly.",
            }
          ),
        ],
      })
    )
    expect(unverifiedHtml).toContain("may or may not have received the submission")
    expect(unverifiedHtml).toContain("https://example.com/one.xml")
    expect(unverifiedHtml).toContain("Unverified")
    expect(unverifiedHtml).toContain("Failed")
  })

  it("renders read-after-write status and complete outcome counts", () => {
    const html = renderPresenter(
      resultActivity({
        results: [
          entry({
            sitemaps: [
              submissionRow({
                outcome: "submitted",
                previously_submitted: true,
                last_submitted: "2026-09-03T12:00:00Z",
                is_pending: true,
                status_read: true,
                warnings: 1,
                errors: 0,
              }),
              submissionRow({
                sitemap_url: "https://example.com/two.xml",
                outcome: "failed",
                error_code: "rejected",
                message: "Google rejected the sitemap submission.",
              }),
            ],
            submitted_count: 1,
            failed_count: 1,
          }),
        ],
      })
    )

    expect(html).toContain("Search Console sitemap submission results")
    expect(html).toContain("Resubmit")
    expect(html).toContain("Pending")
    expect(html).toContain("Sep")
    expect(html).toContain("Google rejected the sitemap submission")
    expect(html).toContain("Submitted")
    expect(html).toContain("Failed")
    expect(html).toContain("Unverified")
  })
})

function renderPresenter(
  toolActivity: ToolActivity,
  approvalDecision?: ToolApprovalDecisionControls
) {
  return render(
    submitSitemapPresenter.render({
      activity: toolActivity,
      ...(approvalDecision ? { approvalDecision } : {}),
      compact: false,
      defaultOpen: true,
      live: false,
      providerKey: "google_search_console",
      ui: UI,
    })
  )
}

function activity(status: ToolActivity["status"], args: unknown): ToolActivity {
  return {
    id: `submit-sitemap-${status}`,
    kind: status === "completed" ? "result" : "call",
    name: "google_search_console_submit_sitemap",
    status,
    args,
  }
}

function resultActivity(result: unknown): ToolActivity {
  return {
    ...activity("completed", ARGS),
    kind: "result",
    result,
  }
}

function entry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "google_search_console",
    display_name: "Example",
    external_id: "https://example.com/",
    status: "success",
    data,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}

function submissionRow(overrides: Record<string, unknown> = {}) {
  return {
    sitemap_url: "https://example.com/one.xml",
    outcome: "submitted",
    previously_submitted: false,
    last_submitted: null,
    is_pending: null,
    warnings: null,
    errors: null,
    status_read: false,
    error_code: null,
    message: null,
    ...overrides,
  }
}

function pendingControls() {
  return controls({ decision: "pending", edits: {}, message: "" })
}

function controls(
  decision: ToolApprovalDecisionControls["decision"]
): ToolApprovalDecisionControls {
  return {
    decision,
    disabled: false,
    error: null,
    onDecisionChange: () => undefined,
    onRetry: () => undefined,
    pendingCount: decision.decision === "pending" ? 1 : 0,
    submitting: false,
  }
}

function render(value: ReactNode) {
  return renderToStaticMarkup(createElement("div", null, value))
}
