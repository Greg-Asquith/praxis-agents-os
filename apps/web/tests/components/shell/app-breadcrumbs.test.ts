import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { AppBreadcrumbs } from "@/components/shell/app-breadcrumbs"

vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useQuery: () => ({ data: undefined }),
}))

vi.mock("@tanstack/react-router", async () => {
  const { createElement } = await import("react")

  return {
    Link: ({ children, to }: { children: ReactNode; to: string }) =>
      createElement("a", { href: to }, children),
  }
})

describe("getBreadcrumbs", () => {
  it.each([
    ["/context", [["Context", undefined]]],
    [
      "/skills",
      [
        ["Context", "/context"],
        ["Skills", undefined],
      ],
    ],
    [
      "/skills/new",
      [
        ["Context", "/context"],
        ["Skills", "/skills"],
        ["New Skill", undefined],
      ],
    ],
    [
      "/skills/skill-id",
      [
        ["Context", "/context"],
        ["Skills", "/skills"],
        ["Skill", undefined],
      ],
    ],
    [
      "/knowledge/document-id",
      [
        ["Context", "/context"],
        ["Knowledge Base", "/knowledge"],
        ["Document", undefined],
      ],
    ],
    [
      "/memories",
      [
        ["Context", "/context"],
        ["Memory", undefined],
      ],
    ],
    [
      "/files",
      [
        ["Context", "/context"],
        ["Files", undefined],
      ],
    ],
    [
      "/artifacts/artifact-id",
      [
        ["Context", "/context"],
        ["Artifacts", "/artifacts"],
        ["Artifact", undefined],
      ],
    ],
    [
      "/integrations/context-groups",
      [
        ["Context", "/context"],
        ["Context Groups", undefined],
      ],
    ],
  ])("re-parents %s under Context", (pathname, expected) => {
    expect(renderedBreadcrumbs(pathname)).toEqual(expected)
  })

  it("keeps provider pages under Integrations", () => {
    expect(renderedBreadcrumbs("/integrations/gmail")).toEqual([
      ["Integrations", "/integrations"],
      ["Gmail", undefined],
    ])
  })
})

function renderedBreadcrumbs(pathname: string) {
  const html = renderToStaticMarkup(
    createElement(AppBreadcrumbs, {
      conversations: [],
      pathname,
    })
  )
  const desktopBreadcrumb =
    /<nav[^>]*aria-label="Breadcrumb"[^>]*>(.*?)<\/nav>/.exec(html)?.[1] ?? ""

  return [...desktopBreadcrumb.matchAll(/<(a|span)([^>]*)>([^<]+)<\/\1>/g)].map((match) => [
    match[3],
    /href="([^"]*)"/.exec(match[2] ?? "")?.[1],
  ])
}
