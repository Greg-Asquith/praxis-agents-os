import { describe, expect, it } from "vitest"

import { fileWindow, mergeListEntries } from "@/features/files/list-entries"
import type { FileFolder, WorkspaceFile } from "@/features/files/types"

function fileAt(id: string, updatedAt: string, size = 10) {
  return { id, name: id, size_bytes: size, updated_at: updatedAt } as WorkspaceFile
}

function folderAt(id: string, updatedAt: string, size = 10) {
  return { id, name: id, total_bytes: size, updated_at: updatedAt } as FileFolder
}

function ids(entries: ReturnType<typeof mergeListEntries>) {
  return entries.map((entry) => (entry.kind === "file" ? entry.file.id : entry.folder.id))
}

describe("fileWindow", () => {
  it("fetches every candidate file without widening past the end of the requested page", () => {
    expect(fileWindow(3, 0, 10)).toEqual({ fileLimit: 10, fileOffset: 0 })
    expect(fileWindow(3, 20, 10)).toEqual({ fileLimit: 13, fileOffset: 17 })
    expect(fileWindow(95, 100, 10)).toEqual({ fileLimit: 105, fileOffset: 5 })
  })
})

describe("mergeListEntries", () => {
  const folders = [folderAt("old-folder", "2026-01-01"), folderAt("new-folder", "2026-03-01")]
  const files = [
    fileAt("newest", "2026-04-01"),
    fileAt("middle", "2026-02-01"),
    fileAt("oldest", "2025-12-01"),
  ]

  it("interleaves folders with files by the sort column", () => {
    const entries = mergeListEntries({
      fileOffset: 0,
      files,
      folders,
      limit: 10,
      offset: 0,
      sortBy: "updated_at",
      sortDirection: "desc",
    })
    expect(ids(entries)).toEqual(["newest", "new-folder", "middle", "old-folder", "oldest"])
  })

  it("compares timestamps by instant across offsets and fractional precision", () => {
    const entries = mergeListEntries({
      fileOffset: 0,
      files: [
        fileAt("newest", "2026-01-01T10:00:00.000100Z"),
        fileAt("oldest", "2026-01-01T10:00:00Z"),
      ],
      folders: [folderAt("middle", "2026-01-01T11:00:00.000050+01:00")],
      limit: 10,
      offset: 0,
      sortBy: "updated_at",
      sortDirection: "desc",
    })
    expect(ids(entries)).toEqual(["newest", "middle", "oldest"])
  })

  it("cuts the requested page out of the fetched window", () => {
    const page = mergeListEntries({
      fileOffset: 0,
      files,
      folders,
      limit: 2,
      offset: 2,
      sortBy: "updated_at",
      sortDirection: "desc",
    })
    expect(ids(page)).toEqual(["middle", "old-folder"])
  })

  it("keeps complete pages when more than 100 candidate files precede the folders", () => {
    const manyFolders = Array.from({ length: 105 }, (_, index) =>
      folderAt(`folder-${String(index)}`, "2025-01-01")
    )
    const manyFiles = Array.from({ length: 150 }, (_, index) =>
      fileAt(`file-${String(index)}`, "2026-01-01")
    )
    const { fileLimit, fileOffset } = fileWindow(manyFolders.length, 110, 10)
    const entries = mergeListEntries({
      fileOffset,
      files: manyFiles.slice(fileOffset, fileOffset + fileLimit),
      folders: manyFolders,
      limit: 10,
      offset: 110,
      sortBy: "updated_at",
      sortDirection: "desc",
    })
    expect(ids(entries)).toEqual(manyFiles.slice(110, 120).map((file) => file.id))
  })

  it.each(["asc", "desc"] as const)(
    "merges mixed-case names in the server's %s order",
    (sortDirection) => {
      const orderedFiles = [fileAt("Zebra", "2026-01-01"), fileAt("apple", "2026-01-01")]
      if (sortDirection === "desc") orderedFiles.reverse()
      const entries = mergeListEntries({
        fileOffset: 0,
        files: orderedFiles,
        folders: [folderAt("banana", "2026-01-01")],
        limit: 10,
        offset: 0,
        sortBy: "name",
        sortDirection,
      })
      const expected = ["Zebra", "apple", "banana"]
      expect(ids(entries)).toEqual(sortDirection === "asc" ? expected : expected.toReversed())
    }
  )

  it.each(["asc", "desc"] as const)(
    "orders non-BMP names by Unicode code points in %s order",
    (sortDirection) => {
      const orderedFiles = [fileAt("\uffff", "2026-01-01"), fileAt("😀b", "2026-01-01")]
      if (sortDirection === "desc") orderedFiles.reverse()
      const entries = mergeListEntries({
        fileOffset: 0,
        files: orderedFiles,
        folders: [folderAt("😀a", "2026-01-01"), folderAt("😀", "2026-01-01")],
        limit: 10,
        offset: 0,
        sortBy: "name",
        sortDirection,
      })
      const expected = ["\uffff", "😀", "😀a", "😀b"]
      expect(ids(entries)).toEqual(sortDirection === "asc" ? expected : expected.toReversed())
    }
  )

  it("follows ascending name and size sorts", () => {
    const byName = mergeListEntries({
      fileOffset: 0,
      files: [fileAt("apple", "2026-01-01"), fileAt("cherry", "2026-01-01")],
      folders: [folderAt("Banana", "2026-01-01")],
      limit: 10,
      offset: 0,
      sortBy: "name",
      sortDirection: "asc",
    })
    expect(ids(byName)).toEqual(["Banana", "apple", "cherry"])

    const bySize = mergeListEntries({
      fileOffset: 0,
      files: [fileAt("small", "2026-01-01", 1), fileAt("large", "2026-01-01", 100)],
      folders: [folderAt("medium", "2026-01-01", 50)],
      limit: 10,
      offset: 0,
      sortBy: "size_bytes",
      sortDirection: "asc",
    })
    expect(ids(bySize)).toEqual(["small", "medium", "large"])
  })
})
