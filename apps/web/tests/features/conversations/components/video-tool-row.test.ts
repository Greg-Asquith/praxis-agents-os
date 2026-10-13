// apps/web/tests/features/conversations/components/video-tool-row.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { filesQueryKeys } from "@/features/files/api/list-files"
import type { WorkspaceFile } from "@/features/files/types"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn((): ToolRowPresenter[] => []))

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

const RESULT = { clips: [{ file_id: "file-1", media_type: "video/mp4", name: "Reel.mp4" }] }

describe("video result row", () => {
  it("plays a completed video result upright with its measurement", () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(filesQueryKeys.detail("file-1"), videoFile())
    queryClient.setQueryData(filesQueryKeys.preview("file-1"), {
      expires_at: "2026-10-13T12:10:00Z",
      preview: { url: "https://storage.test/reel.mp4?signed=1" },
    })

    const html = render(queryClient, renderCustomToolCallRow(props()))

    expect(html).toContain('src="https://storage.test/reel.mp4?signed=1"')
    expect(html).toContain("1080 x 1920")
  })

  it("leaves a result to a specific presenter that claims it", () => {
    integrationToolRowPresenters.mockReturnValueOnce([
      {
        key: "provider",
        matches: () => true,
        render: () => createElement("p", null, "Provider row"),
      },
    ])

    const html = render(new QueryClient(), renderCustomToolCallRow(props()))

    expect(html).toContain("Provider row")
    expect(html).not.toContain("<video")
  })
})

function render(queryClient: QueryClient, row: ReactNode) {
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: queryClient }, row))
}

function props(): ToolRowPresenterProps {
  return {
    activity: {
      id: "tool-1",
      kind: "result",
      name: "cut_video_clips",
      result: RESULT,
      status: "completed",
    },
    compact: false,
    defaultOpen: true,
    label: "Cut Video Clips",
    live: false,
    providerKey: null,
    ui: null,
  }
}

function videoFile(): WorkspaceFile {
  return {
    id: "file-1",
    workspace_id: "workspace-1",
    scope: "workspace",
    is_published: false,
    can_manage_platform: false,
    published_revision_id: null,
    name: "Reel.mp4",
    description: null,
    folder_id: null,
    folder_name: null,
    category: "video",
    content_type: "video/mp4",
    extension: "mp4",
    size_bytes: 1_000_000,
    content_hash: "hash",
    current_revision_id: "revision-1",
    revision_count: 1,
    processing_status: "ready",
    processing_error: null,
    // Portrait phone footage: landscape frames with a rotation flag.
    video: {
      duration_ms: 62_000,
      width: 1920,
      height: 1080,
      fps: 30,
      has_audio: true,
      rotation: 90,
    },
    created_at: "2026-10-13",
    updated_at: "2026-10-13",
  }
}
