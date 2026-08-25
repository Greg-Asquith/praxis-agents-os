import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { SkillAvailabilitySection } from "@/features/skills/components/skill-availability-section"

describe("SkillAvailabilitySection", () => {
  it("renders favorites for workspace skills", () => {
    const html = renderToStaticMarkup(
      createElement(SkillAvailabilitySection, {
        isActive: "true",
        isFavorite: "true",
        onActiveChange: vi.fn(),
        onFavoriteChange: vi.fn(),
        showFavorite: true,
      })
    )

    expect(html).toContain("Status")
    expect(html).toContain("Active")
    expect(html).toContain("Favorite")
  })

  it("hides favorites for platform skills", () => {
    const html = renderToStaticMarkup(
      createElement(SkillAvailabilitySection, {
        isActive: "true",
        isFavorite: "false",
        onActiveChange: vi.fn(),
        onFavoriteChange: vi.fn(),
        showFavorite: false,
      })
    )

    expect(html).not.toContain("Favorite")
  })
})
