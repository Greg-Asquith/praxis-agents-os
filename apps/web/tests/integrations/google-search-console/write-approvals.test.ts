// apps/web/tests/integrations/google-search-console/write-approvals.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ToolApprovalDecisionControls } from "@/components/tool-ui/approval-card"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolUi } from "@/features/tools/types"
import { googleSearchConsoleRequestIndexingPresenter } from "@/integrations/google_search_console/presenters/request-indexing"
import { googleSearchConsoleSubmitSitemapPresenter } from "@/integrations/google_search_console/presenters/submit-sitemap"

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
})

describe("Search Console Indexing API write presenter", () => {
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
})

function renderPresenter(
  toolActivity: ToolActivity,
  approvalDecision?: ToolApprovalDecisionControls
) {
  return render(
    googleSearchConsoleSubmitSitemapPresenter.render({
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
    googleSearchConsoleRequestIndexingPresenter.render({
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

function indexingActivity(status: ToolActivity["status"]): ToolActivity {
  return {
    id: `request-indexing-${status}`,
    kind: status === "completed" ? "result" : "call",
    name: "google_search_console_request_indexing",
    status,
    args: INDEXING_ARGS,
  }
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
