import { afterEach, describe, expect, it } from "vitest"

import { skillMutationQueryKey, skillsQueryKeys } from "@/features/skills/api/list-skills"
import { setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  setActiveUserId(null)
  setActiveWorkspaceSlug(null)
})

describe("skill mutation query keys", () => {
  it("invalidates only the active workspace for workspace skills", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("workspace-a")

    expect(skillMutationQueryKey("workspace")).toEqual(skillsQueryKeys.workspace())
  })

  it("invalidates every cached workspace for platform skills", () => {
    expect(skillMutationQueryKey("platform")).toEqual(skillsQueryKeys.all)
  })
})
