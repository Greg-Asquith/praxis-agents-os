// apps/web/src/features/files/components/folder-copy.ts

import type { FileFolder } from "../types"

export function folderDeleteDescription(folder: Pick<FileFolder, "file_count">) {
  return `Delete folder and its ${String(folder.file_count)} ${folder.file_count === 1 ? "file" : "files"}?`
}

export function moveFilesDescription(fileCount: number) {
  return `Choose where to keep ${fileCount === 1 ? "this file" : `${String(fileCount)} files`}.`
}
