import { describe, expect, it } from "vitest"

import {
  internalSkillLabelFromCapabilityArgs,
  skillIdFromCapabilityArgs,
} from "@/features/conversations/skills/skill-activation"

describe("skill activation capability ids", () => {
  it("labels internal skills from their name and keeps them apart from workspace skills", () => {
    const internalArgs = '{"id":"internal-skill-authoring"}'

    expect(internalSkillLabelFromCapabilityArgs(internalArgs)).toBe("Skill authoring")
    expect(skillIdFromCapabilityArgs(internalArgs)).toBeNull()
    expect(internalSkillLabelFromCapabilityArgs({ id: "skill-research" })).toBeNull()
  })
})
