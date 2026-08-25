import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { AgentSkillsSection } from "@/features/agents/components/agent-skills-section"
import type { Skill } from "@/features/skills/types"

const platformSkill: Skill = {
  id: "platform-skill",
  name: "shared-research",
  human_name: "Shared research",
  description: "Shared research guidance.",
  instructions: "Use verified sources.",
  scope: "platform",
  workspace_id: null,
  created_by: "admin-1",
  documentation_refs: {},
  is_active: true,
  is_favorite: false,
  last_used_at: null,
  metadata: null,
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:00:00Z",
  deleted: false,
  deleted_at: null,
}

describe("AgentSkillsSection", () => {
  it("identifies platform choices and paginates the available catalog", () => {
    const html = renderToStaticMarkup(
      createElement(AgentSkillsSection, {
        limit: 50,
        offset: 0,
        onPageChange: vi.fn(),
        setField: vi.fn(),
        skillIds: [],
        skills: [platformSkill],
        total: 120,
      })
    )

    expect(html).toContain("Available skills pagination")
    expect(html).toContain("Showing 1-50 of 120")
  })

  it("keeps an attached skill identifiable when it is outside the current catalog page", () => {
    const html = renderToStaticMarkup(
      createElement(AgentSkillsSection, {
        limit: 50,
        offset: 50,
        onPageChange: vi.fn(),
        setField: vi.fn(),
        skillIds: [platformSkill.id],
        skills: [platformSkill],
        total: 120,
      })
    )

    expect(html).toContain("Shared research")
    expect(html).toContain("Platform")
    expect(html).not.toContain("Unavailable skill")
  })
})
