import { describe, expect, it } from "vitest"

import {
  internalSkillLabelFromCapabilityArgs,
  loadedSkillNameFromArgs,
  skillActivationDisplayName,
} from "@/features/conversations/skills/skill-activation"

describe("skill activation labels", () => {
  it("labels internal skills from their capability id and loaded skills from their name", () => {
    expect(internalSkillLabelFromCapabilityArgs('{"id":"internal-skill-authoring"}')).toBe(
      "Skill authoring"
    )
    expect(internalSkillLabelFromCapabilityArgs({ id: "skill-research" })).toBeNull()

    const name = loadedSkillNameFromArgs('{"name":"weekly-report"}')
    expect(name).toBe("weekly-report")
    expect(skillActivationDisplayName(undefined, name ?? "")).toBe("Weekly report")
    expect(
      skillActivationDisplayName({ human_name: "Weekly Report", name: "weekly-report" }, "x")
    ).toBe("Weekly Report")
  })
})
