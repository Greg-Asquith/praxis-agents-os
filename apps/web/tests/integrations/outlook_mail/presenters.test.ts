// apps/web/tests/integrations/outlook_mail/presenters.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"

function render(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } })
  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement("div", null, node))
  )
}

const node = (content: string) => ({
  node: "praxis_untrusted",
  source_kind: "outlook_message",
  source_ref: "message",
  content,
})
const message = {
  reference: {
    version: 1,
    entity_kind: "outlook_message",
    mailbox_id: "mailbox",
    message_id: "message",
    label: "Outlook message",
  },
  subject: node("Monthly report"),
  from: { name: node("Dana"), address: node("dana@example.com") },
  received_at: "2026-09-08T10:00:00Z",
  is_read: false,
  has_attachments: true,
  preview: node("Report preview"),
}
const cases = [
  ["search_messages", { messages: [message], count: 1 }, "Report preview"],
  [
    "read_message",
    {
      ...message,
      body: node("Report body"),
      to: [{ name: node("Kai"), address: node("kai@example.com") }],
      attachments: [{ name: node("report.pdf") }],
      truncated: true,
    },
    "Report body",
  ],
  [
    "list_folders",
    {
      folders: [
        { name: node("Invoices"), unread_count: 2, total_count: 10, child_folder_count: 0 },
      ],
    },
    "Invoices",
  ],
  [
    "search_people",
    {
      people: [
        {
          name: node("Dana"),
          address: node("dana@example.com"),
          job_title: node("Analyst"),
          department: node("Operations"),
        },
      ],
    },
    "Analyst",
  ],
  [
    "read_attachment",
    { name: node("report.pdf"), markdown: node("# Revenue\nMonthly revenue"), truncated: true },
    "Monthly revenue",
  ],
] as const

describe("Outlook read results", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["outlook_mail"])
  })

  describe.each(["success", "error", "partial"])("%s results", (mode) => {
    it.each(cases)("renders %s from the registered presenter", (tool, data, expected) => {
      const row = renderCustomToolCallRow({
        activity: {
          id: "call",
          kind: "result",
          name: `outlook_mail_${tool}`,
          status: "completed",
          result: {
            results: [
              {
                provider_key: "outlook_mail",
                external_id: "mailbox",
                display_name: "Operations mailbox",
                status: "success",
                data,
              },
              {
                provider_key: "outlook_mail",
                external_id: "other",
                display_name: "Other mailbox",
                status: "error",
                data: null,
                error_code: "permission_denied",
                error_message: "Mailbox access denied",
              },
            ].filter((entry) => mode === "partial" || entry.status === mode),
          },
        },
        compact: false,
        defaultOpen: true,
        live: false,
        providerKey: "outlook_mail",
        ui: null,
      })
      expect(row).not.toBeNull()
      const html = render(row)
      if (mode !== "error") expect(html).toContain(expected)
      if (mode !== "success") expect(html).toContain("Mailbox access denied")
      expect(html).not.toContain("praxis_untrusted")
      expect(html).not.toContain("connection_id")
    })
  })

  it("shows message flags, the result count, and the search inputs", () => {
    const html = render(
      renderCustomToolCallRow({
        activity: {
          id: "call",
          kind: "result",
          name: "outlook_mail_search_messages",
          status: "completed",
          args: { query: "invoice", folder: "sentitems", unread_only: true, limit: 5 },
          result: {
            results: [
              {
                provider_key: "outlook_mail",
                external_id: "mailbox",
                display_name: "Operations mailbox",
                status: "success",
                data: { messages: [{ ...message, importance: "high" }], count: 1 },
              },
            ],
          },
        },
        compact: false,
        defaultOpen: true,
        live: false,
        providerKey: "outlook_mail",
        ui: null,
      })
    )
    expect(html).toContain("Search Outlook Mail")
    expect(html).toContain("Dana &lt;dana@example.com&gt;")
    expect(html).toContain("1 Message")
    expect(html).toContain("Unread")
    expect(html).toContain("High importance")
    expect(html).toContain("Attachment")
    expect(html).toContain("Folder: Sent Items")
    expect(html).toContain("Search: invoice")
    expect(html).toContain("Filter: Unread only")
    expect(html).toContain("Up to 5 messages")
    expect(html).toContain('role="list"')
  })
})

const recordCases = [
  [
    "list_folders",
    "folders",
    { name: node("Invoices"), unread_count: 2, total_count: 10, child_folder_count: 0 },
    "No folders found.",
  ],
  [
    "search_people",
    "people",
    {
      name: node("Dana"),
      address: node("dana@example.com"),
      job_title: node("Analyst"),
      department: node("Operations"),
    },
    "No people found.",
  ],
] as const

describe.each(recordCases)("%s record validation", (tool, key, valid, emptyLabel) => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["outlook_mail"])
  })
  function renderRecords(records: unknown) {
    return renderCustomToolCallRow({
      activity: {
        id: "call",
        kind: "result",
        name: `outlook_mail_${tool}`,
        status: "completed",
        result: {
          results: [
            {
              provider_key: "outlook_mail",
              external_id: "mailbox",
              display_name: "Mailbox",
              status: "success",
              data: { [key]: records },
            },
          ],
        },
      },
      compact: false,
      defaultOpen: true,
      live: false,
      providerKey: "outlook_mail",
      ui: null,
    })
  }
  it("renders empty results", () => {
    expect(render(renderRecords([]))).toContain(emptyLabel)
  })
  it.each([null, [null], [{}], [{ ...valid, name: 7 }]])(
    "rejects malformed records: %s",
    (records) => {
      expect(renderRecords(records)).toBeNull()
    }
  )
  it("contains long text in the shared table without exposing internal fields", () => {
    const long = "long".repeat(500)
    const html = render(
      renderRecords([
        {
          ...valid,
          name: node(long),
          connection_id: "private-connection",
          internal: { token: "private-token" },
        },
      ])
    )
    expect(html).toContain(long)
    expect(html).toContain("truncate")
    expect(html).not.toMatch(/praxis_untrusted|private-connection|private-token|source_ref/)
  })
  it("enforces field-specific types", () => {
    if (key === "people") {
      for (const field of ["address", "job_title", "department"]) {
        expect(renderRecords([{ ...valid, [field]: 7 }])).toBeNull()
      }
    } else {
      expect(renderRecords([{ ...valid, unread_count: 7 }])).not.toBeNull()
      expect(renderRecords([{ ...valid, unread_count: "7" }])).toBeNull()
      expect(renderRecords([{ ...valid, unread_count: -1 }])).toBeNull()
    }
  })
})
