import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { SkillIdentitySection } from "@/features/skills/components/skill-identity-section"

function renderIdentitySection(canSetPlatformScope: boolean) {
  return renderToStaticMarkup(
    createElement(SkillIdentitySection, {
      canSetPlatformScope,
      description: "",
      fieldErrors: {},
      isPlatform: false,
      mode: "create",
      name: "",
      onDescriptionChange: vi.fn(),
      onNameChange: vi.fn(),
      onPlatformChange: vi.fn(),
    })
  )
}

describe("SkillIdentitySection", () => {
  it("places the platform scope checkbox in the identity section for super admins", () => {
    const html = renderIdentitySection(true)

    expect(html).toContain("Make available to every workspace")
    expect(html).toContain("skill-platform-scope")
    expect(html.indexOf("skill-description")).toBeLessThan(html.indexOf("skill-platform-scope"))
  })

  it("hides the platform scope checkbox from other users", () => {
    expect(renderIdentitySection(false)).not.toContain("Make available to every workspace")
  })
})
