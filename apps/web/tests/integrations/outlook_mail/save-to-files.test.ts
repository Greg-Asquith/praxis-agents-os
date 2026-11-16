// apps/web/tests/integrations/outlook_mail/save-to-files.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it } from "vitest"

import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { workspaceFilePreviewQueryOptions } from "@/components/tool-ui/workspace-file-preview"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { loadIntegrationUiModules } from "@/integrations/registry"

const FILE_ID = "019927a2-1891-7123-8123-0123456789ab"

function render(node: ReactNode, client = new QueryClient()) {
  client.setDefaultOptions({ queries: { retry: false, enabled: false } })
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(ToolConversationContext, { value: "conversation" }, node)
    )
  )
}

function row(tool: string, data: unknown) {
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
            data,
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

const attachment = (name: string, inline: boolean) => ({
  reference: {
    version: 1,
    entity_kind: "outlook_attachment",
    mailbox_id: "mailbox",
    message_id: "message",
    attachment_id: name,
    label: "Outlook attachment",
  },
  name,
  content_type: inline ? "image/png" : "application/pdf",
  size_bytes: 2048,
  is_inline: inline,
})

describe("Outlook Save to Files", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["outlook_mail"])
  })

  it("offers View and Save to Files on attachments and collapses inline images", () => {
    const html = render(
      row("read_message", {
        reference: {
          version: 1,
          entity_kind: "outlook_message",
          mailbox_id: "mailbox",
          message_id: "message",
          label: "Outlook message",
        },
        subject: "Contract",
        from: { name: "Dana", address: "dana@example.com" },
        received_at: "2026-09-08T10:00:00Z",
        is_read: true,
        has_attachments: true,
        preview: "Signed copy",
        body: "Signed copy attached",
        to: [],
        attachments: [attachment("contract.pdf", false), attachment("logo.png", true)],
        truncated: false,
      })
    )
    expect(html).toContain('aria-label="View contract.pdf"')
    expect(html).toContain('aria-label="Save contract.pdf to Files"')
    expect(html).toContain("Show 1 Inline Image")
    expect(html).not.toContain("logo.png")
  })

  it("plays a saved image in place from its Files preview", () => {
    const client = new QueryClient()
    client.setQueryData(workspaceFilePreviewQueryOptions(FILE_ID, null).queryKey, {
      preview: { url: "https://storage.test/photo.png" },
    })
    const html = render(
      row("save_attachment", {
        file_id: FILE_ID,
        name: "photo.png",
        content_type: "image/png",
        size_bytes: 2048,
      }),
      client
    )
    expect(html).toContain('src="https://storage.test/photo.png"')
  })
})
