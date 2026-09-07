// apps/web/tests/integrations/google-search-console/write-approvals.test.ts

import { createElement, isValidElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolUi } from "@/features/tools/types"
import { requestIndexingPresenter } from "@/integrations/google_search_console/presenters/request-indexing"
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

const INDEXING_UI: ToolUi = {
  icon: "google_search_console",
  running_label: "Sending Search Console Indexing Notifications",
  completed_label: "Sent Search Console Indexing Notifications",
  failed_label: "Couldn't Send Search Console Indexing Notifications",
  approval_title: "Send Indexing API Notifications",
  approval_prompt:
    "Google accepts these notifications only for job posting pages and livestream video pages. Notifications for other pages are ignored and may violate Google's guidelines. A URL_DELETED notification asks Google to remove the page from its index. Before approving one, confirm that the page returns 404 or 410, or includes a noindex directive. Google decides when and whether to crawl, index, or remove each page.",
  approve_label: "Approve & Notify",
  arg_fields: [
    {
      key: "notifications",
      label: "Notifications",
      min_rows: 1,
      format: "records",
      editable: true,
      placeholder: "",
      options: [],
      secondary: false,
      columns: [
        { key: "url", label: "URL", options: [], placeholder: "", required: true },
        {
          key: "notification_type",
          label: "Notification",
          options: ["URL_UPDATED", "URL_DELETED"],
          placeholder: "",
          required: true,
        },
        {
          key: "page_type",
          label: "Eligible Page Type",
          options: ["job_posting", "broadcast_event"],
          placeholder: "",
          required: true,
        },
      ],
    },
  ],
  result_fields: UI.result_fields,
}

const INDEXING_ARGS = {
  notifications: [
    {
      url: "https://example.com/jobs/one",
      notification_type: "URL_UPDATED",
      page_type: "job_posting",
    },
  ],
  _indexing_writable_sites: ["https://example.com/"],
}

describe("Search Console sitemap write presenter", () => {
  it("fails closed for malformed retained approvals and preserves provenance", () => {
    const malformed = renderPresenter(activity("awaiting_approval", null), pendingControls())
    expect(malformed).toContain("Decline this request, then ask the agent")
    const sources = [{ source_kind: "integration", source_ref: "source-page" }]
    const node = submitSitemapPresenter.render({
      activity: {
        ...activity("awaiting_approval", ARGS),
        derivedFromUntrusted: true,
        taintSources: sources,
      },
      providerKey: "google_search_console",
      approvalDecision: pendingControls(),
      compact: false,
      defaultOpen: true,
      live: false,
      ui: UI,
    })
    expect(isValidElement(node)).toBe(true)
    if (isValidElement<{ derivedFromUntrusted: boolean; taintSources: unknown }>(node)) {
      expect(node.props.derivedFromUntrusted).toBe(true)
      expect(node.props.taintSources).toEqual(sources)
    }
  })

  it("keeps lifecycle states and malformed results distinct", () => {
    expect(renderPresenter(activity("running", ARGS))).toContain(
      "Submitting Search Console sitemaps"
    )
    expect(renderPresenter(activity("awaiting_approval", ARGS))).toContain(
      "Waiting for sitemap submission approval"
    )
    expect(renderPresenter(activity("unknown", ARGS))).toContain(
      "No sitemap submission was confirmed"
    )
    expect(renderPresenter(resultActivity({ results: [entry({ invalid: true })] }))).toContain(
      "Failed"
    )
    const mixed = renderPresenter(
      resultActivity({
        results: [
          entry({ sitemaps: [submissionRow()], submitted_count: 1, failed_count: 0 }),
          entry(null, {
            display_name: "Second site",
            status: "error",
            error_message: "Site unavailable",
          }),
        ],
      })
    )
    expect(mixed).toContain("1/2 connections")
    expect(mixed).toContain("https://example.com/one.xml")
    expect(mixed).toContain("Site unavailable")
  })

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

describe("Search Console Indexing API write presenter", () => {
  it("shows the eligibility limit and editable notification records", () => {
    const html = renderIndexingPresenter(indexingActivity("awaiting_approval"), pendingControls())

    expect(html).toContain("Send Indexing API Notifications")
    expect(html).toContain("only for job posting pages and livestream video pages")
    expect(html).toContain("may violate Google&#x27;s guidelines")
    expect(html).toContain("asks Google to remove the page from its index")
    expect(html).toContain("returns 404 or 410")
    expect(html).toContain("noindex directive")
    expect(html).toContain("Remove row 1")
    expect(html).toContain("Approve &amp; Notify")
  })

  it("rejects edited URLs outside the selected writable sites", () => {
    const html = renderIndexingPresenter(
      indexingActivity("awaiting_approval"),
      controls({
        decision: "pending",
        edits: {
          notifications: [
            {
              url: "https://other.example/jobs/one",
              notification_type: "URL_UPDATED",
              page_type: "job_posting",
            },
          ],
        },
        message: "",
      })
    )

    expect(html).toContain("must belong to one of the selected writable Search Console sites")
  })

  it("renders notify times and actionable provider errors", () => {
    const html = renderIndexingPresenter(
      indexingResultActivity({
        results: [
          entry({
            notifications: [
              indexingRow(),
              indexingRow({
                url: "https://example.com/jobs/two",
                outcome: "failed",
                notify_time: null,
                error_code: "quota_exhausted",
                message: null,
              }),
            ],
            notified_count: 1,
            failed_count: 1,
          }),
        ],
      })
    )

    expect(html).toContain("Search Console Indexing API notification results")
    expect(html).toContain("Job Posting")
    expect(html).toContain("Updated")
    expect(html).toContain("Sep")
    expect(html).toContain("limit of 200 notifications per day")
    expect(html).toContain("Notified")
    expect(html).toContain("Failed")
  })

  it("keeps declined and unverified outcomes explicit", () => {
    const denied = indexingActivity("denied")
    denied.decisionReason = "Confirm the structured data first."
    const deniedHtml = renderIndexingPresenter(denied)
    expect(deniedHtml).toContain("Nothing was sent")
    expect(deniedHtml).toContain("Confirm the structured data first")
    expect(deniedHtml).toContain("Declined")

    const unverifiedHtml = renderIndexingPresenter(
      indexingResultActivity({
        results: [
          entry(
            {
              notifications: [
                indexingRow({ outcome: "unverified", notify_time: null, error_code: "unverified" }),
              ],
              notified_count: 0,
              failed_count: 0,
            },
            {
              status: "error",
              error_code: "unverified_mutation",
              error_message: "The notification outcome could not be verified exactly.",
            }
          ),
        ],
      })
    )
    expect(unverifiedHtml).toContain("may or may not have received the notification")
    expect(unverifiedHtml).toContain("Unverified")
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

function renderIndexingPresenter(
  toolActivity: ToolActivity,
  approvalDecision?: ToolApprovalDecisionControls
) {
  return render(
    requestIndexingPresenter.render({
      activity: toolActivity,
      ...(approvalDecision ? { approvalDecision } : {}),
      compact: false,
      defaultOpen: true,
      live: false,
      providerKey: "google_search_console",
      ui: INDEXING_UI,
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

function indexingActivity(status: ToolActivity["status"]): ToolActivity {
  return {
    id: `request-indexing-${status}`,
    kind: status === "completed" ? "result" : "call",
    name: "google_search_console_request_indexing",
    status,
    args: INDEXING_ARGS,
  }
}

function indexingResultActivity(result: unknown): ToolActivity {
  return { ...indexingActivity("completed"), kind: "result", result }
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

function indexingRow(overrides: Record<string, unknown> = {}) {
  return {
    url: "https://example.com/jobs/one",
    notification_type: "URL_UPDATED",
    page_type: "job_posting",
    outcome: "notified",
    notify_time: "2026-09-03T12:00:00Z",
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
