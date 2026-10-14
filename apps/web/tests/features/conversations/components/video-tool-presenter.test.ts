// apps/web/tests/features/conversations/components/video-tool-presenter.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  RouterContextProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router"
import { describe, expect, it, vi } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { filesQueryKeys } from "@/features/files/api/list-files"
import type { VideoMetadata } from "@/features/files/types"
import type { ToolRowPresenter } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn((): ToolRowPresenter[] => []))

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

const LANDSCAPE: VideoMetadata = {
  duration_ms: 83_500,
  width: 1920,
  height: 1080,
  fps: 30,
  has_audio: true,
  rotation: 0,
}

function untrusted(content: string) {
  return { node: "praxis_untrusted", source_kind: "video_moment", source_ref: "file:f", content }
}

describe("video tool rows", () => {
  it("plays a completed video result upright with its measurement", () => {
    const html = render(
      "cut_video_clips",
      {
        clips: [{ file_id: "file-1", media_type: "video/mp4", name: "Reel.mp4" }],
      },
      { ...LANDSCAPE, rotation: 90 }
    )

    expect(html).toContain('src="https://storage.test/file-1.mp4?signed=1"')
    expect(html).toContain("1080 x 1920")
  })

  it("leaves a video result to a specific presenter that claims it", () => {
    integrationToolRowPresenters.mockReturnValueOnce([
      { key: "provider", matches: () => true, render: () => createElement("p", null, "Provider") },
    ])

    const html = render("upload_video", { file_id: "file-1", media_type: "video/mp4" })

    expect(html).toBe("<p>Provider</p>")
  })

  it("plays the selected moment's range from the source video", () => {
    const html = render("find_video_moments", {
      name: "Talk.mp4",
      file_id: "file-1",
      moments: [
        {
          start_ms: 37_240,
          end_ms: 63_240,
          start: "0:37",
          end: "1:03",
          score: 92,
          shot_count: 1,
          title: untrusted("Setting Up the Skill"),
        },
      ],
    })

    expect(html).toContain('src="https://storage.test/file-1.mp4?signed=1#t=37.24,63.24"')
  })

  it("plays the range an answer watched", () => {
    const html = render("ask_video", {
      name: "Talk.mp4",
      file_id: "file-1",
      start_ms: 600_000,
      end_ms: 720_000,
      start: "10:00",
      end: "12:00",
      answer: untrusted("At 10:30 the slide reads **Per seat**."),
    })

    expect(html).toContain("#t=600,720")
  })

  it("shows a still of each saved clip and links the folder they went to", () => {
    const html = render("cut_video_clips", {
      saved: 1,
      clips: [
        {
          index: 1,
          status: "saved",
          name: "Talk 0.41-1.10.mp4",
          file_id: "file-1",
          media_type: "video/mp4",
          duration_ms: 29_000,
          folder: { id: "folder-1", name: "Talk" },
          segments: [{ file_id: "source-1", start: "0:41", end: "1:10" }],
        },
      ],
    })

    expect(html).toContain('src="https://storage.test/file-1.mp4?signed=1#t=0.1"')
    expect(html).toContain('href="/files?folder=folder-1"')
  })
})

function render(name: string, result: unknown, video: VideoMetadata = LANDSCAPE) {
  const queryClient = new QueryClient()
  queryClient.setQueryData(filesQueryKeys.detail("file-1"), {
    id: "file-1",
    name: "Talk.mp4",
    category: "video",
    processing_status: "ready",
    processing_error: null,
    size_bytes: 1_000,
    video,
  })
  queryClient.setQueryData(filesQueryKeys.preview("file-1"), {
    expires_at: "2026-10-13T12:10:00Z",
    preview: { url: "https://storage.test/file-1.mp4?signed=1" },
  })
  const row = renderCustomToolCallRow({
    activity: { id: "tool-1", kind: "result", name, args: {}, result, status: "completed" },
    compact: false,
    defaultOpen: true,
    label: name,
    live: false,
    providerKey: null,
    ui: null,
  })
  const rootRoute = createRootRoute()
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([
      createRoute({ getParentRoute: () => rootRoute, path: "/files" }),
    ]),
  })
  return renderToStaticMarkup(
    createElement(RouterContextProvider, {
      router,
      children: createElement(QueryClientProvider, { client: queryClient }, row),
    })
  )
}
