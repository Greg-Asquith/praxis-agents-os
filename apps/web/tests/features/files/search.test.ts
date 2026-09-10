import { describe, expect, it } from "vitest"

import { validateFilesSearch } from "@/features/files/search"

describe("validateFilesSearch", () => {
  it("keeps valid paging, sorting, and file detail state", () => {
    expect(
      validateFilesSearch({
        direction: "asc",
        fileId: "file-1",
        folder: "folder-1",
        page: "3",
        q: "  board update  ",
        sort: "name",
      })
    ).toEqual({
      direction: "asc",
      fileId: "file-1",
      folder: "folder-1",
      page: 3,
      q: "board update",
      sort: "name",
    })
  })

  it("retains scope filters and drops unknown scope values", () => {
    expect(validateFilesSearch({ scope: "platform" })).toEqual({ scope: "platform" })
    expect(validateFilesSearch({ scope: "workspace" })).toEqual({ scope: "workspace" })
    expect(validateFilesSearch({ scope: "all" })).toEqual({})
    expect(validateFilesSearch({ scope: "private" })).toEqual({})
  })

  it("drops defaults and invalid values", () => {
    expect(
      validateFilesSearch({
        direction: "sideways",
        fileId: 42,
        folder: 42,
        page: 1,
        q: "   ",
        sort: "created_at",
      })
    ).toEqual({})
  })
})
