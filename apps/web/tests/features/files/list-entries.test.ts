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
})
