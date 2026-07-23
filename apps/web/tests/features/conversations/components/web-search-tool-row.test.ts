import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { WebSearchToolRow } from "@/features/conversations/components/web-search-tool-row"
import { webSearchResult } from "@/features/conversations/components/web-search-result"
import type { ToolActivity } from "@/features/conversations/message-parts"

describe("WebSearchToolRow", () => {
  it("uses the query as the running headline with a search skeleton", () => {
    const html = render({
      id: "search-1",
      kind: "call",
      name: "web_search",
      status: "running",
      args: { query: "Praxis Agents" },
    })

    expect(html).toContain("Praxis Agents")
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Searching Praxis Agents…")
  })

  it("renders provider sources as a bounded list with safe external links", () => {
    const html = render({
      id: "search-1",
      kind: "result",
      name: "web_search",
      status: "completed",
      result: {
        model: "gpt-5.6-luna",
        model_provider: "openai",
        query: "Praxis Agents",
        sources: [
          {
            title: {
              node: "praxis_untrusted",
              source_kind: "web_search",
              source_ref: "https://docs.example.com/praxis",
              content: "<strong>Praxis documentation</strong>",
            },
            snippet: {
              node: "praxis_untrusted",
              source_kind: "web_search",
              source_ref: "https://docs.example.com/praxis",
              content: "<script>alert('no')</script>",
            },
            url: "https://www.docs.example.com/praxis",
          },
        ],
      },
    })

    expect(html).toContain("Praxis Agents")
    expect(html).toContain("Web Search")
    expect(html).toContain("1 Result")
    expect(html).toContain("openai")
    expect(html).toContain("gpt-5.6-luna")
    expect(html).toContain(">Details<")
    expect(html).toContain("&lt;strong&gt;Praxis documentation&lt;/strong&gt;")
    expect(html).toContain("&lt;script&gt;alert(&#x27;no&#x27;)&lt;/script&gt;")
    expect(html).toContain("docs.example.com")
    expect(html).toContain('href="https://www.docs.example.com/praxis"')
    expect(html).toContain('rel="noreferrer"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('aria-label="Web sources"')
    expect(html).toContain("overflow-y-auto")
    expect(html).toContain('aria-label="Collapse results"')
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("Done")
    expect(html).not.toContain("<script>")
  })

  it("falls back for malformed results and unsafe URLs", () => {
    expect(
      webSearchResult({
        query: "unsafe",
        sources: [{ title: "Bad source", url: "javascript:alert(1)" }],
      })
    ).toBeNull()
    expect(webSearchResult({ query: "missing sources" })).toBeNull()
  })
})

function render(activity: ToolActivity): string {
  return renderToStaticMarkup(createElement(WebSearchToolRow, { activity }))
}
