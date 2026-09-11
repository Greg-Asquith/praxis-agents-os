import { describe, expect, it } from "vitest"

import {
  describeArtifactSaveError,
  isStaleArtifactError,
  publicationLabel,
} from "@/features/artifacts/format"
import { ApiError } from "@/lib/api/errors"

function apiError(status: number, message: string) {
  return new ApiError({ status, message, problem: null })
}

describe("publicationLabel", () => {
  it("labels only unpublished platform artifacts", () => {
    expect(publicationLabel({ scope: "workspace", is_published: false })).toBeNull()
    expect(publicationLabel({ scope: "platform", is_published: true })).toBeNull()
    expect(
      publicationLabel({ scope: "platform", is_published: false, published_version_id: "v1" })
    ).toBe("Withdrawn")
    expect(
      publicationLabel({ scope: "platform", is_published: false, published_version_id: null })
    ).toBe("Unpublished")
  })
})

describe("stale artifact errors", () => {
  it("treats only conflicts as stale reviews", () => {
    expect(isStaleArtifactError(apiError(409, "Conflict"))).toBe(true)
    expect(isStaleArtifactError(apiError(403, "Forbidden"))).toBe(false)
    expect(isStaleArtifactError(new Error("Conflict"))).toBe(false)
  })

  it("explains a stale review and passes other messages through", () => {
    expect(describeArtifactSaveError(apiError(409, "Conflict"))).toContain(
      "changed since you opened it"
    )
    expect(describeArtifactSaveError(apiError(403, "Editors only"))).toBe("Editors only")
  })
})
