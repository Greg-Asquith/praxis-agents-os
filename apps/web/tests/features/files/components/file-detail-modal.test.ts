import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { FileDetailModal } from "@/features/files/components/file-detail-modal"
import { platformFileQueryOptions } from "@/features/files/api/platform-get-file"
import { filesQueryKeys } from "@/features/files/api/list-files"
import { ActiveWorkspaceContext } from "@/features/workspaces/components/active-workspace-context"
import type { Workspace } from "@/features/workspaces/types"
import type { WorkspaceFile } from "@/features/files/types"

vi.mock("@/components/ui/dialog", () => {
  const part = ({ children }: PropsWithChildren) => createElement("div", null, children)
  return {
    Dialog: ({ children, open }: PropsWithChildren<{ open?: boolean }>) =>
      open ? createElement("div", null, children) : null,
    DialogClose: part,
    DialogContent: part,
    DialogDescription: part,
    DialogFooter: part,
    DialogHeader: part,
    DialogTitle: part,
  }
})
vi.mock("@/features/files/components/file-attach-button", () => ({ FileAttachButton: () => null }))
vi.mock("@/features/files/components/file-revisions-list", () => ({
  FileRevisionsList: () => null,
}))
vi.mock("@/features/files/components/rename-file-dialog", () => ({ RenameFileDialog: () => null }))
vi.mock("@/features/files/components/move-files-dialog", () => ({ MoveFilesDialog: () => null }))

const file: WorkspaceFile = {
  id: "platform-file",
  scope: "platform",
  workspace_id: null,
  is_published: true,
  can_manage_platform: false,
  published_revision_id: "revision",
  name: "Guidance.mp3",
  description: null,
  folder_id: null,
  folder_name: null,
  category: "audio",
  content_type: "audio/mpeg",
  extension: "mp3",
  size_bytes: 100,
  content_hash: "hash",
  current_revision_id: "revision",
  revision_count: 1,
  processing_status: "ready",
  processing_error: null,
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-10T10:00:00Z",
}
const workspace: Workspace = {
  id: "workspace",
  slug: "example",
  name: "Example",
  icon_url: null,
  is_personal: false,
  status: "active",
  current_user_role: "member",
  created_at: file.created_at,
  updated_at: file.updated_at,
  deleted: false,
  deleted_at: null,
}

beforeEach(() => vi.clearAllMocks())

function renderDetail(
  role: Workspace["current_user_role"],
  target = file,
  platformManagement = false
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(filesQueryKeys.revisions(target.id), { revisions: [], total: 0 })
  if (platformManagement) client.setQueryData(platformFileQueryOptions(target.id).queryKey, target)
  return renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client,
      children: createElement(ActiveWorkspaceContext, {
        value: {
          workspace: { ...workspace, current_user_role: role },
          workspaces: [],
          setWorkspaceBySlug: () => undefined,
        },
        children: createElement(FileDetailModal, {
          fileId: target.id,
          platformManagement,
          initialFile: target,
          open: true,
          onOpenChange: () => undefined,
        }),
      }),
    })
  )
}

describe("platform File detail", () => {
  it("shows admin processing details without unavailable tenant actions", () => {
    const html = renderDetail(
      "member",
      { ...file, is_published: false, processing_status: "processing" },
      true
    )
    expect(html).toContain(file.name)
    expect(html).toContain("Preparing this file")
    expect(html).not.toContain("Download")
    expect(html).not.toContain("Make a workspace copy")
  })
  it("retains ordinary actions for published admin entries", () => {
    const html = renderDetail("member", file, true)
    expect(html).toContain("Download")
    expect(html).toContain("Make a workspace copy")
  })
  it("shows the audience and local copy action without platform mutations", () => {
    const html = renderDetail("member")
    expect(html).toContain("Platform")
    expect(html).toContain("available in every workspace")
    expect(html).toContain("Make a workspace copy</button>")
    expect(html).toContain("Download")
    expect(html).toContain("View")
    expect(html).not.toContain("Rename Guidance")
    expect(html).not.toContain("Move to")
    expect(html).not.toContain("Folder: ")
  })
  it.each(["read_only", null] as const)("hides local copy for membership %s", (role) => {
    const html = renderDetail(role)
    expect(html).not.toContain("Make a workspace copy</button>")
    expect(html).toContain("Download")
  })
  it("keeps workspace editing available to members", () => {
    const html = renderDetail("member", {
      ...file,
      scope: "workspace",
      workspace_id: workspace.id,
      is_published: false,
    })
    expect(html).toContain("Rename Guidance")
    expect(html).toContain("Move to")
    expect(html).not.toContain("Make a workspace copy</button>")
  })
})
