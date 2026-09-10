// apps/web/src/features/files/list-entries.ts

import type {
  FileFolder,
  FileSortDirection,
  FileSortField,
  WorkspaceFile,
} from "@/features/files/types"

export type FileListEntry =
  { file: WorkspaceFile; kind: "file" } | { folder: FileFolder; kind: "folder" }

// Folders live in the browser while files page on the server, so a page of the
// merged list needs every file that could land in it once folders are mixed in.
export function fileWindow(folderCount: number, offset: number, limit: number) {
  const fileOffset = Math.max(0, offset - folderCount)
  return { fileLimit: offset + limit - fileOffset, fileOffset }
}

// Merges folders into a server-sorted page of files and cuts out the requested window.
export function mergeListEntries({
  fileOffset,
  files,
  folders,
  limit,
  offset,
  sortBy,
  sortDirection,
}: {
  fileOffset: number
  files: WorkspaceFile[]
  folders: FileFolder[]
  limit: number
  offset: number
  sortBy: FileSortField
  sortDirection: FileSortDirection
}): FileListEntry[] {
  const compare = entryComparator(sortBy, sortDirection)
  const pending = folders.map((folder): FileListEntry => ({ folder, kind: "folder" })).sort(compare)
  const merged: FileListEntry[] = []
  let folderIndex = 0
  for (const file of files) {
    const entry: FileListEntry = { file, kind: "file" }
    let next = pending[folderIndex]
    while (next && compare(next, entry) <= 0) {
      merged.push(next)
      folderIndex += 1
      next = pending[folderIndex]
    }
    merged.push(entry)
  }
  // Position in `merged` is the true list position minus fileOffset, so the slice below
  // drops folders that fall outside the fetched window.
  merged.push(...pending.slice(folderIndex))
  return merged.slice(Math.max(0, offset - fileOffset), offset - fileOffset + limit)
}

function entryComparator(sortBy: FileSortField, sortDirection: FileSortDirection) {
  const sign = sortDirection === "asc" ? 1 : -1
  return (a: FileListEntry, b: FileListEntry) => {
    const left = entryValue(a, sortBy)
    const right = entryValue(b, sortBy)
    if (left === right) return 0
    if (typeof left === "string" && typeof right === "string") {
      return (sortBy === "name" ? compareText(left, right) : compareTimestamps(left, right)) * sign
    }
    return left < right ? -sign : sign
  }
}

function entryValue(entry: FileListEntry, sortBy: FileSortField) {
  const item = entry.kind === "file" ? entry.file : entry.folder
  if (sortBy === "name") return item.name
  if (sortBy === "size_bytes") {
    return entry.kind === "file" ? entry.file.size_bytes : entry.folder.total_bytes
  }
  return item.updated_at
}

// PostgreSQL's C collation orders UTF-8 by code point, not JavaScript's UTF-16 units.
function compareText(left: string, right: string) {
  let index = 0
  while (index < left.length && index < right.length) {
    const leftPoint = left.codePointAt(index) ?? 0
    const rightPoint = right.codePointAt(index) ?? 0
    if (leftPoint !== rightPoint) return leftPoint - rightPoint
    index += leftPoint > 0xffff ? 2 : 1
  }
  return left.length - right.length
}

function compareTimestamps(left: string, right: string) {
  const difference = Date.parse(left) - Date.parse(right)
  if (difference !== 0) return difference

  // Date.parse truncates the API's microseconds to milliseconds.
  const leftFraction = Number(`0.${/\.(\d+)/.exec(left)?.[1] ?? "0"}`)
  const rightFraction = Number(`0.${/\.(\d+)/.exec(right)?.[1] ?? "0"}`)
  return leftFraction - rightFraction
}
