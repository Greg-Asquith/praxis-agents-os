import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Checkbox } from "@/components/ui/checkbox"

describe("Checkbox", () => {
  it("renders the shared Base UI control", () => {
    const checkbox = renderToStaticMarkup(createElement(Checkbox, { checked: true }))

    expect(checkbox).toContain('data-slot="checkbox"')
    expect(checkbox).toContain('aria-checked="true"')
  })
})
