// apps/web/tests/features/conversations/components/video-clips-row.test.ts

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
import type { ToolRowPresenter } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn((): ToolRowPresenter[] => []))

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

describe("cut video clips row", () => {
  it("shows a still of each saved clip, links its folder, and explains a failed one", () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(filesQueryKeys.detail("clip-1"), {
      id: "clip-1",
      name: "Talk 0.41-1.10.mp4",
      category: "video",
      processing_status: "ready",
      processing_error: null,
      size_bytes: 1_000,
      video: { duration_ms: 29_000, width: 1080, height: 1920, fps: 30, has_audio: true },
    })
    queryClient.setQueryData(filesQueryKeys.preview("clip-1"), {
      expires_at: "2026-10-13T12:10:00Z",
      preview: { url: "https://storage.test/clip-1.mp4?signed=1" },
    })
    const segment = { file_id: "file-1", start: "0:41", end: "1:10" }
    const row = renderCustomToolCallRow({
      activity: {
        id: "tool-1",
        kind: "result",
        name: "cut_video_clips",
        args: { aspect_ratio: "9:16" },
        result: {
          count: 2,
          saved: 1,
          failed: 1,
          clips: [
            {
              index: 1,
              status: "saved",
              name: "Talk 0.41-1.10.mp4",
              file_id: "clip-1",
              media_type: "video/mp4",
              duration_ms: 29_000,
              folder: { id: "folder-1", name: "Talk" },
              segments: [
                segment,
                {
                  ...segment,
                  transition_in: { style: "wipeleft", duration_ms: 400, audio_curve: "tri" },
                },
              ],
              fade_in_ms: 500,
              fade_out_ms: 0,
              warnings: [],
            },
            {
              index: 2,
              status: "failed",
              name: "Talk 2.00-2.30.mp4",
              error: "The video couldn't be read.",
              segments: [segment],
              warnings: [],
            },
          ],
        },
        status: "completed",
      },
      compact: false,
      defaultOpen: true,
      label: "cut_video_clips",
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
    const html = renderToStaticMarkup(
      createElement(RouterContextProvider, {
        router,
        children: createElement(QueryClientProvider, { client: queryClient }, row),
      })
    )

    expect(html).toContain('src="https://storage.test/clip-1.mp4?signed=1#t=0.1"')
    expect(html).toContain('href="/files?folder=folder-1"')
    expect(html).toContain("The video couldn&#x27;t be read.")
    expect(html).toContain("Fade In 0.5 s · Wipe Left 0.4 s")
  })
})
