import { createElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { AdPreview } from "@/integrations/meta_ads/components/ad-preview"

describe("Meta Ads ad preview", () => {
  // The threat model's adversarial fixture for model-written ad text.
  it("renders model-written text as plain text in both placements", () => {
    const hostile = '<img src=x onerror="alert(1)">Sale'
    for (const placement of ["feed", "stories"] as const) {
      const html = renderToStaticMarkup(
        createElement(
          QueryClientProvider,
          { client: new QueryClient() },
          createElement(AdPreview, {
            placement,
            pageName: hostile,
            pageId: null,
            format: "image",
            primaryText: hostile,
            headline: hostile,
            description: hostile,
            callToAction: "SHOP_NOW",
            domain: "example.com",
            media: null,
            verticalMedia: null,
            cards: [],
          })
        )
      )

      expect(html).not.toContain("<img src=x")
      expect(html).toContain("&lt;img src=x")
    }
  })
})
