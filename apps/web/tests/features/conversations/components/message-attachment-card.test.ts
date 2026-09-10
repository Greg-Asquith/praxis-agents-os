import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import type { MessageAttachment } from "@/features/conversations/attachments"
import { MessageAttachmentCard } from "@/features/conversations/components/message-attachment-card"
import { fileQueryOptions } from "@/features/files/api/get-file"
import type { WorkspaceFile } from "@/features/files/types"

const attachment: MessageAttachment = {
  fileId: "file-1",
  mediaType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  name: null,
}

const workspaceFile: WorkspaceFile = {
  id: "file-1",
  workspace_id: "workspace-1",
  scope: "workspace",
  is_published: false,
  can_manage_platform: false,
  published_revision_id: null,
  name: "August report.pptx",
  description: null,
  folder_id: null,
  folder_name: null,
  category: "ingestible_document",
  content_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  extension: ".pptx",
  size_bytes: 554_989,
  content_hash: "hash",
  current_revision_id: "revision-1",
  revision_count: 1,
  processing_status: "ready",
  processing_error: null,
  created_at: "2026-08-25T18:00:00Z",
  updated_at: "2026-08-25T18:00:00Z",
}

describe("MessageAttachmentCard", () => {
  it("renders the fetched filename and type label for a history attachment", () => {
    const queryClient = createQueryClient()
    queryClient.setQueryData(fileQueryOptions(attachment.fileId).queryKey, workspaceFile)

    const html = renderAttachment(queryClient)

    expect(html).toContain("August report.pptx")
    expect(html).toContain("PowerPoint")
    expect(html).toContain(workspaceFile.content_type)
  })

  it("labels a fetched platform attachment", () => {
    const queryClient = createQueryClient()
    queryClient.setQueryData(fileQueryOptions(attachment.fileId).queryKey, {
      ...workspaceFile,
      scope: "platform",
      workspace_id: null,
      is_published: true,
    })
    expect(renderAttachment(queryClient)).toContain(">Platform<")
  })

  it("keeps the platform label for an attachment with known metadata", () => {
    const html = renderToStaticMarkup(
      createElement(QueryClientProvider, {
        client: createQueryClient(),
        children: createElement(MessageAttachmentCard, {
          attachment: { ...attachment, name: "August report.pptx", scope: "platform" },
        }),
      })
    )

    expect(html).toContain("August report.pptx")
    expect(html).toContain(">Platform<")
  })

  it("shows the persisted media type while file metadata is loading", () => {
    const html = renderAttachment(createQueryClient())

    expect(html).toContain(attachment.mediaType)
    expect(html).not.toContain("August report.pptx")
  })

  it("keeps the media type fallback when the file lookup returns 404", async () => {
    const queryClient = createQueryClient()
    await expect(
      queryClient.fetchQuery({
        ...fileQueryOptions(attachment.fileId),
        queryFn: () => Promise.reject(new Error("404 Not Found")),
      })
    ).rejects.toThrow("404 Not Found")

    const html = renderAttachment(queryClient)

    expect(html).toContain(attachment.mediaType)
    expect(html).not.toContain("404 Not Found")
  })
})

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
}

function renderAttachment(queryClient: QueryClient) {
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client: queryClient,
      children: createElement(MessageAttachmentCard, { attachment }),
    })
  )
}
