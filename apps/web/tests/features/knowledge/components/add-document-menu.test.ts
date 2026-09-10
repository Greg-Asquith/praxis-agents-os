// apps/web/tests/features/knowledge/components/add-document-menu.test.ts

import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AddDocumentMenu } from "@/features/knowledge/components/add-document-menu"

const state = vi.hoisted(() => ({ loading: true, error: false }))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useSuspenseQuery: () => ({ data: { id: "user" } }),
  useQuery: () => ({
    data: undefined,
    isPending: state.loading,
    isError: state.error,
    refetch: vi.fn(),
  }),
}))
vi.mock("@/components/ui/dropdown-menu", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  // Render portal content during server rendering while retaining real menu and group context.
  DropdownMenuContent: ({ children }: PropsWithChildren) => createElement("div", null, children),
}))

beforeEach(() => {
  state.loading = true
  state.error = false
})

describe("Add Document integration status", () => {
  it("renders the loading label within the required Base UI group", () => {
    const html = renderToStaticMarkup(createElement(AddDocumentMenu))
    expect(html).toContain("Loading import options…")
    expect(html).toContain('data-slot="dropdown-menu-group"')
  })

  it("renders the failed catalogue label and retry control within the required Base UI group", () => {
    state.loading = false
    state.error = true
    const html = renderToStaticMarkup(createElement(AddDocumentMenu))
    expect(html).toContain("Import options unavailable.")
    expect(html).toContain("Try Again")
    expect(html).toContain('data-slot="dropdown-menu-group"')
    expect(html).not.toContain("Loading import options…")
  })

  it("does not load workspace integration options when adding platform content", () => {
    const html = renderToStaticMarkup(createElement(AddDocumentMenu, { platform: true }))
    expect(html).toContain("Write Manually")
    expect(html).toContain("Upload Document")
    expect(html).not.toContain("Loading import options…")
    expect(html).not.toContain("Add from URL")
  })
})
