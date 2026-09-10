import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { FileAttachButton } from "@/features/files/components/file-attach-button"
import type { WorkspaceFile } from "@/features/files/types"

vi.mock("@tanstack/react-router", () => ({
  Link: ({ search, children }: { search: { file: string }; children: React.ReactNode }) =>
    createElement("a", { href: `/conversations/new?file=${search.file}` }, children),
}))

const file = {
  id: "file-1",
  scope: "platform",
  is_published: true,
  category: "editable_text",
} as WorkspaceFile

describe("FileAttachButton", () => {
  it("opens a new conversation with the published File selected", () => {
    const html = renderToStaticMarkup(createElement(FileAttachButton, { file }))
    expect(html).toContain("/conversations/new?file=file-1")
    expect(html).toContain("Add to chat")
  })

  it("allows HTML files stored as editable text", () => {
    expect(
      renderToStaticMarkup(
        createElement(FileAttachButton, {
          file: { ...file, content_type: "text/html", category: "editable_text" },
        })
      )
    ).toContain("Add to chat")
  })

  it("allows workspace documents and hides unavailable or unsupported Files", () => {
    expect(
      renderToStaticMarkup(
        createElement(FileAttachButton, {
          file: { ...file, scope: "workspace", is_published: false },
        })
      )
    ).toContain("Add to chat")
    for (const unavailable of [
      { ...file, is_published: false },
      { ...file, category: "video" as const },
      { ...file, category: "audio" as const },
    ]) {
      expect(renderToStaticMarkup(createElement(FileAttachButton, { file: unavailable }))).toBe("")
    }
  })
})
