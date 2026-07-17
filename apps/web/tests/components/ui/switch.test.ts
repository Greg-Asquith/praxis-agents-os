import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Switch } from "@/components/ui/switch"

describe("Switch", () => {
  it("keeps a complete track around the thumb at each size", () => {
    const defaultSwitch = renderToStaticMarkup(createElement(Switch))
    const smallSwitch = renderToStaticMarkup(createElement(Switch, { size: "sm" }))

    expect(defaultSwitch).toContain("data-[size=default]:w-8")
    expect(smallSwitch).toContain("data-[size=sm]:w-6")
  })
})
