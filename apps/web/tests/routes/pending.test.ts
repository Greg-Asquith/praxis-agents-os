import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { PendingRoute } from "@/routes/pending"

describe("PendingRoute", () => {
  it("explains that Praxis is starting and continues automatically", () => {
    const html = renderToStaticMarkup(createElement(PendingRoute))

    expect(html).toContain('role="status"')
    expect(html).toContain("Starting up")
    expect(html).toContain("The system is getting ready")
    expect(html).toContain("continues automatically")
    expect(html).toContain("min-h-dvh")
  })
})
