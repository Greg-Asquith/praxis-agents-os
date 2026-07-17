import { describe, expect, it } from "vitest"

import { validateFilesSearch } from "@/features/files/search"

describe("validateFilesSearch", () => {
  it("keeps valid paging, sorting, and file detail state", () => {
    expect(
      validateFilesSearch({
        direction: "asc",
        fileId: "file-1",
        page: "3",
        sort: "name",
      })
    ).toEqual({
      direction: "asc",
      fileId: "file-1",
      page: 3,
      sort: "name",
    })
  })

  it("drops defaults and invalid values", () => {
    expect(
      validateFilesSearch({
        direction: "sideways",
        fileId: 42,
        page: 1,
        sort: "content_hash",
      })
    ).toEqual({})
  })
})
