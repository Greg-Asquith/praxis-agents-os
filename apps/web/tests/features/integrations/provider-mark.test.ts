import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ProviderMark } from "@/features/integrations/components/provider-mark"

describe("ProviderMark", () => {
  it("has a bounded default size while allowing explicit size overrides", () => {
    const defaultMark = renderToStaticMarkup(
      createElement(ProviderMark, { providerKey: "google_ads" })
    )
    const compactMark = renderToStaticMarkup(
      createElement(ProviderMark, { className: "size-3.5", providerKey: "gmail" })
    )

    expect(defaultMark).toContain("size-4")
    expect(compactMark).toContain("size-3.5")
    expect(compactMark).not.toContain("size-4")
  })
})
