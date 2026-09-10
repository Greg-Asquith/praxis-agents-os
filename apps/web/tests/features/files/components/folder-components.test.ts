import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { FolderHeader } from "@/features/files/components/folder-header"
import {
  folderDeleteDescription,
  folderFileCountLabel,
  moveFilesDescription,
} from "@/features/files/components/folder-copy"
import { NewFolderButton } from "@/features/files/components/new-folder-button"
import type { FileFolder } from "@/features/files/types"

const folder: FileFolder = {
  created_at: "2026-08-18T09:00:00Z",
  description: "Launch collateral",
  file_count: 3,
  id: "folder-1",
  name: "Launch pack",
  total_bytes: 4096,
  updated_at: "2026-08-18T10:00:00Z",
  workspace_id: "workspace-1",
}

function renderWithQueryClient(element: ReturnType<typeof createElement>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(createElement(QueryClientProvider, { client, children: element }))
}

describe("file folder components", () => {
  it("renders the new-folder action independently for the page header", () => {
    const html = renderWithQueryClient(createElement(NewFolderButton))

    expect(html).toContain("New Folder")
  })

  it("renders the folder breadcrumb and destructive action trigger", () => {
    const html = renderWithQueryClient(
      createElement(FolderHeader, {
        folder,
        onDeleted: () => undefined,
      })
    )

    expect(html).toContain("Actions for Launch pack")
    expect(html).not.toContain("&gt;Launch pack&lt;")
  })

  it("formats counts, move, and destructive confirmations", () => {
    expect(folderFileCountLabel({ file_count: 1 })).toBe("1 file")
    expect(folderFileCountLabel(folder)).toBe("3 files")
    expect(moveFilesDescription(1)).toBe("Choose where to keep this file.")
    expect(moveFilesDescription(3)).toBe("Choose where to keep 3 files.")
    expect(folderDeleteDescription(folder)).toBe("Delete folder and its 3 files?")
  })
})
