import { describe, expect, it } from "vitest"

import { validateArtifactDetailSearch, validateArtifactsSearch } from "@/features/artifacts/search"

describe("validateArtifactsSearch", () => {
  it("keeps only supported list state and trims the query", () => {
    expect(
      validateArtifactsSearch({
        direction: "asc",
        page: "3",
        q: "  launch  ",
        scope: "platform",
        sort: "title",
      })
    ).toEqual({ direction: "asc", page: 3, q: "launch", scope: "platform", sort: "title" })
  })

  it("drops defaults, unknown values, and the first page", () => {
    expect(
      validateArtifactsSearch({
        direction: "sideways",
        page: 1,
        q: "",
        scope: "all",
        sort: "size_bytes",
        platform: true,
      })
    ).toEqual({})
  })
})

describe("validateArtifactDetailSearch", () => {
  it("accepts only literal true flags", () => {
    expect(validateArtifactDetailSearch({ edit: true, platform: "true" })).toEqual({ edit: true })
    expect(validateArtifactDetailSearch({ platform: true })).toEqual({ platform: true })
  })
})
