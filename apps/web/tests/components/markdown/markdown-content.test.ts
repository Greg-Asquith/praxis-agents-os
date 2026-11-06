// apps/web/tests/components/markdown/markdown-content.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { MarkdownContent } from "@/components/markdown/markdown-content"

function render(content: string): string {
  return renderToStaticMarkup(createElement(MarkdownContent, { content }))
}

describe("MarkdownContent", () => {
  it("strips app classes from untrusted HTML so it can't overlay the UI", () => {
    const markup = render(
      '<div class="fixed inset-0 z-50 bg-background p-8"><a class="fixed inset-0" href="https://example.invalid">Sign in again</a></div>'
    )

    expect(markup).toContain("Sign in again")
    expect(markup).not.toMatch(/\b(fixed|inset-0|z-50|bg-background)\b/)
  })

  it("keeps the classes code blocks and task lists need", () => {
    const markup = render("```ts\nconst a = 1\n```\n\n- [x] done\n- [ ] todo")

    expect(markup).toContain(">ts</span>")
    expect(markup).toMatch(/<ul class="[^"]*list-none/)
  })
})
