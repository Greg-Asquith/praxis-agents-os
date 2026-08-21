import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { webFetchResult } from "@/features/conversations/components/web-fetch-result"
import { webFetchToolPresenter } from "@/features/conversations/components/web-fetch-tool-presenter"
import type { ToolActivity } from "@/features/conversations/message-parts"
import type { ToolRowPresenterProps } from "@/integrations/contract"

describe("WebFetchToolRow", () => {
  it("shows the exact URL while fetching", () => {
    const html = render({
      id: "fetch-1",
      kind: "call",
      name: "fetch_url",
      status: "running",
      args: { url: "https://docs.example.com/page?approved=yes" },
    })

    expect(
      webFetchToolPresenter.matches(activityFromUrl("https://docs.example.com/page?approved=yes"))
    ).toBe(true)
    expect(html).toContain("https://docs.example.com/page?approved=yes")
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Web Fetch")
  })

  it("renders framed page text as markdown and links provider sources", () => {
    const html = render({
      id: "fetch-1",
      kind: "result",
      name: "fetch_url",
      status: "completed",
      result: {
        content: {
          node: "praxis_untrusted",
          source_kind: "web_fetch",
          source_ref: "https://docs.example.com/page",
          content: "# Praxis documentation\n\nSafe **page content**.",
        },
        model: "claude-sonnet-5",
        model_provider: "anthropic",
        sources: [{ title: "Praxis docs", url: "https://docs.example.com/page" }],
        url: "https://docs.example.com/page",
      },
    })

    expect(webFetchToolPresenter.matches(completedActivity())).toBe(true)
    expect(html).toContain("Praxis documentation")
    expect(html).toContain(">page content</strong>")
    expect(html).toContain("Fetched Page Content")
    expect(html).toContain("Praxis docs")
    expect(html).toContain('href="https://docs.example.com/page"')
    expect(html).toContain("anthropic")
    expect(html).toContain("claude-sonnet-5")
    expect(html).toContain('aria-label="Fetched page content"')
    expect(html).toContain('aria-label="Fetched page sources"')
    expect(html).toContain("overscroll-contain")
    expect(html).not.toContain("praxis_untrusted")
  })

  it("rejects malformed structured results and unsafe source URLs", () => {
    expect(
      webFetchResult({
        content: "page",
        model: "model",
        model_provider: "provider",
        sources: [{ title: "Unsafe", url: "javascript:alert(1)" }],
        url: "https://safe.example",
      })
    ).toBeNull()
    expect(webFetchResult({ content: "page" })).toBeNull()
  })
})

function render(activity: ToolActivity): string {
  return renderToStaticMarkup(webFetchToolPresenter.render(presenterProps(activity)))
}

function presenterProps(activity: ToolActivity): ToolRowPresenterProps {
  return {
    activity,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: null,
  }
}

function activityFromUrl(url: string): ToolActivity {
  return { id: "fetch-1", kind: "call", name: "fetch_url", status: "running", args: { url } }
}

function completedActivity(): ToolActivity {
  return {
    id: "fetch-1",
    kind: "result",
    name: "fetch_url",
    status: "completed",
    result: {
      content: {
        node: "praxis_untrusted",
        source_kind: "web_fetch",
        source_ref: "https://docs.example.com/page",
        content: "# Praxis documentation",
      },
      model: "claude-sonnet-5",
      model_provider: "anthropic",
      sources: [],
      url: "https://docs.example.com/page",
    },
  }
}
