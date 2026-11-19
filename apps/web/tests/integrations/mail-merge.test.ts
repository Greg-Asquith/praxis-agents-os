// apps/web/tests/integrations/mail-merge.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  extraColumns,
  fillMergeTemplate,
  mailMergeProblem,
  parseMailMergeArgs,
  type MailMergeArgs,
} from "@/integrations/mail-merge"
import { mailMergeQueryOptions, type MailMergeProgress } from "@/integrations/mail-merge-api"
import { MailMergeApprovalSummary } from "@/integrations/mail-merge-approval"
import { MailMergeProgressCard } from "@/integrations/mail-merge-progress"

const PROPOSED = {
  subject: "Hello {{first_name}}",
  body_html: "<p>Hi {{first_name|there}}</p>",
  recipients: [{ email: "dana@example.com", first_name: "Dana" }],
  _mailbox: { address: "sasha@example.org", connection_id: "connection-1" },
  _merge: {
    recipients: [
      {
        position: 0,
        email: "dana@example.com",
        status: "ready",
        problems: [],
        warnings: [],
        skip_reason: null,
      },
    ],
    budget: { cap: 1000, remaining: 999, frees_at: null },
    interval_seconds: 3,
    estimated_finish: "2026-11-18T14:40:00Z",
    needs_reconnect: false,
    template_problem: null,
  },
}
const TESTED = {
  ...PROPOSED,
  _test: {
    sent_to: "sasha@example.org",
    recipient: "dana@example.com",
    sent_at: "2026-11-18T14:00:00Z",
  },
  _reviewed: { subject: PROPOSED.subject, body_html: PROPOSED.body_html, fallbacks: null },
}

function parsed(value: unknown): MailMergeArgs {
  const args = parseMailMergeArgs(value)
  if (!args) throw new Error("Mail merge args didn't parse")
  return args
}

describe("mail merge approval", () => {
  it("blocks approval until a test of the current content, and again after an edit", () => {
    expect(mailMergeProblem(parsed(PROPOSED), "Gmail")).not.toBeNull()
    expect(mailMergeProblem(parsed(TESTED), "Gmail")).toBeNull()
    expect(
      mailMergeProblem(parsed({ ...TESTED, body_html: "<p>Hello {{first_name}}</p>" }), "Gmail")
    ).not.toBeNull()
    expect(
      mailMergeProblem(parsed({ ...TESTED, fallbacks: { first_name: "there" } }), "Gmail")
    ).not.toBeNull()
  })

  it("keeps each row's check when another row is removed, and lets a changed row be tested", () => {
    const check = (email: string, status: string) => ({
      position: 0,
      email,
      status,
      problems: [],
      warnings: [],
      skip_reason: null,
    })
    const merge = {
      ...PROPOSED._merge,
      recipients: [check("bad", "needs_attention"), check("dana@example.com", "ready")],
    }

    const removed = parsed({ ...TESTED, _merge: merge })
    expect(removed.checks.map((row) => row?.status)).toEqual(["ready"])
    expect(mailMergeProblem(removed, "Gmail")).toBeNull()

    const corrected = parsed({
      ...TESTED,
      recipients: [{ email: "dana@example.org", first_name: "Dana" }],
    })
    expect(corrected.checks).toEqual([null])
    expect(mailMergeProblem(corrected, "Gmail")).toBeNull()
  })

  it("fills a placeholder named like a built-in property from the row, not the prototype", () => {
    expect(fillMergeTemplate("{{constructor|x}} {{toString}}", {}, {}, false)).toEqual({
      text: "x ",
      missing: ["toString"],
    })
  })

  it("escapes recipient values in the previewed body but keeps template HTML", () => {
    const filled = fillMergeTemplate(
      "<p>Hi {{first_name}} from {{company|us}} {{city}}</p>",
      { first_name: "<script>x</script>" },
      {},
      true
    )

    expect(filled.text).toBe("<p>Hi &lt;script&gt;x&lt;/script&gt; from us </p>")
    expect(filled.missing).toEqual(["city"])
  })

  it("offers a column for each new placeholder or fallback so rows can fill it in", () => {
    const args = parsed({
      ...PROPOSED,
      subject: "{{ team }} news for {{first_name}}",
      body_html: "<p>Hi {{first_name}} at {{company|your company}}</p>",
      fallbacks: { city: "your city", last_name: "" },
      recipients: [{ email: "dana@example.com", fields: { role: "Lead" } }],
    })

    expect(extraColumns(args)).toEqual(["role", "team", "company", "city"])
  })

  it("renders the card with the recipients, preview and test button", () => {
    const html = renderToStaticMarkup(
      createElement(MailMergeApprovalSummary, {
        args: parsed(PROPOSED),
        controls: {
          decision: { decision: "pending", edits: {}, message: "" },
          error: null,
          onDecisionChange: () => undefined,
          onRetry: () => undefined,
          onReview: () => undefined,
          pendingCount: 1,
          submitting: false,
        },
        disabled: false,
        onFieldEdit: () => undefined,
      })
    )

    expect(html).toContain("dana@example.com")
  })
})

describe("mail merge progress", () => {
  it("renders a finished merge with its results and no controls", () => {
    const progress: MailMergeProgress = {
      id: "merge-1",
      provider_key: "gmail",
      sender_address: "sasha@example.org",
      status: "completed",
      stop_reason: null,
      created_at: "2026-11-19T10:50:00Z",
      finished_at: "2026-11-19T10:57:00Z",
      estimated_finish: null,
      resumes_at: null,
      counts: { total: 2, waiting: 0, sent: 1, failed: 0, unverified: 1, skipped: 0 },
      recipients: [
        {
          position: 0,
          email: "dana@example.com",
          state: "sent",
          reason: null,
          sent_at: "2026-11-19T10:56:00Z",
        },
        { position: 1, email: "kai@example.com", state: "unverified", reason: null, sent_at: null },
      ],
    }
    const client = new QueryClient()
    client.setQueryData(mailMergeQueryOptions("merge-1").queryKey, progress)

    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client },
        createElement(MailMergeProgressCard, {
          providerName: "Gmail",
          result: {
            mergeId: "merge-1",
            sender: "sasha@example.org",
            sendingTo: 2,
            estimatedFinish: null,
          },
        })
      )
    )

    expect(html).toContain("kai@example.com")
  })
})
