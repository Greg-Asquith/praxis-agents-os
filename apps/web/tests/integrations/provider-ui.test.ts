// apps/web/tests/integrations/provider-ui.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { IntegrationToolHeading, type IntegrationProviderUi } from "@/integrations/provider-ui"

const provider: IntegrationProviderUi = {
  contextLabel: "Project",
  externalLabel: null,
  fallbackDisplayName: "Selected project",
  Logo: (props) => createElement("svg", { ...props, "data-testid": "example-logo" }),
  name: "Example",
  providerKey: "example",
}

describe("integration tool heading", () => {
  it("renders the provider mark beside compact heading text", () => {
    const html = renderToStaticMarkup(
      createElement(IntegrationToolHeading, { children: "Loading Example", provider })
    )

    expect(html).toContain("text-sm")
    expect(html).toContain("font-medium")
    expect(html).toContain('data-testid="example-logo"')
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain("Loading Example")
  })
})
