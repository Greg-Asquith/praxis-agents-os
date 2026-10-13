// apps/web/tests/features/conversations/components/video-understanding-row.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import { filesQueryKeys } from "@/features/files/api/list-files"
import type { ToolRowPresenter, ToolRowPresenterProps } from "@/integrations/contract"

const integrationToolRowPresenters = vi.hoisted(() => vi.fn((): ToolRowPresenter[] => []))

vi.mock("@/integrations/registry", () => ({ integrationToolRowPresenters }))

function untrusted(content: string) {
  return { node: "praxis_untrusted", source_kind: "video_moment", source_ref: "file:f", content }
}

const MOMENTS = {
  name: "Talk.mp4",
  file_id: "file-1",
  count: 1,
  moments: [
    {
      start_ms: 37_240,
      end_ms: 63_240,
      start: "0:37",
      end: "1:03",
      score: 92,
      shot_count: 1,
      title: untrusted("Setting Up the Skill"),
      hook: untrusted("So I'm going to hit new skill."),
      reason: untrusted("Shows the setup."),
      transcript_excerpt: untrusted("So I'm going to hit new skill and fill in this form."),
    },
  ],
}

describe("video understanding rows", () => {
  it("plays the selected moment's range from the source video", () => {
    const html = render(row("find_video_moments", MOMENTS))

    expect(html).toContain('src="https://storage.test/talk.mp4?signed=1#t=37.24,63.24"')
  })

  it("plays the range an answer watched", () => {
    const html = render(
      row(
        "ask_video",
        {
          name: "Talk.mp4",
          file_id: "file-1",
          start_ms: 600_000,
          end_ms: 720_000,
          start: "10:00",
          end: "12:00",
          answer: untrusted("At 10:30 the slide reads **Per seat**."),
        },
        { question: "What does the slide say?" }
      )
    )

    expect(html).toContain("#t=600,720")
  })
})

function render(node: ReactNode) {
  const queryClient = new QueryClient()
  queryClient.setQueryData(filesQueryKeys.detail("file-1"), {
    id: "file-1",
    name: "Talk.mp4",
    category: "video",
    processing_status: "ready",
    processing_error: null,
    size_bytes: 1_000,
    video: {
      duration_ms: 83_500,
      width: 1920,
      height: 1080,
      fps: 30,
      has_audio: true,
      rotation: 0,
    },
  })
  queryClient.setQueryData(filesQueryKeys.preview("file-1"), {
    expires_at: "2026-10-13T12:10:00Z",
    preview: { url: "https://storage.test/talk.mp4?signed=1" },
  })
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: queryClient }, node))
}

function row(name: string, result: unknown, args: unknown = {}) {
  const props: ToolRowPresenterProps = {
    activity: { id: "tool-1", kind: "result", name, args, result, status: "completed" },
    compact: false,
    defaultOpen: true,
    label: name,
    live: false,
    providerKey: null,
    ui: null,
  }
  return renderCustomToolCallRow(props)
}
