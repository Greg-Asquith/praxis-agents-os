// apps/web/tests/integrations/google-ads/upload-media.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  editFiles,
  editVideoText,
  madeWithAiIds,
  parseUploadMediaArgs,
  serializeCancelled,
  uploadBlock,
  youtubeVideoId,
} from "@/integrations/google_ads/lib/upload-media"
import { googleAdsUploadMediaPresenter } from "@/integrations/google_ads/presenters/upload-media"

const SQUARE = { entity_kind: "file", entity_id: "f-1", label: "logo-mark.png" }
const LARGE = { entity_kind: "file", entity_id: "f-2", label: "trail-hero-wide.png" }
const VIDEO = { entity_kind: "file", entity_id: "f-3", label: "trail-fit-launch.mp4" }
const VIDEO_CHECK = {
  kind: "video",
  file_id: "f-3",
  revision_id: "r-f-3",
  content_hash: "def",
  name: "trail-fit-launch.mp4",
  content_type: "video/mp4",
  size_bytes: 48_000_000,
  duration_ms: 32_000,
  default_title: "trail-fit-launch.mp4",
  problem: null,
}

function check(fileId: string, extra: Record<string, unknown> = {}) {
  return {
    file_id: fileId,
    revision_id: `r-${fileId}`,
    content_hash: "abc",
    name: fileId === "f-1" ? "logo-mark.png" : "trail-hero-wide.png",
    content_type: "image/png",
    size_bytes: 65_536,
    width: 400,
    height: 400,
    fits: ["SQUARE_MARKETING_IMAGE", "LOGO"],
    too_small: [],
    problem: null,
    ...extra,
  }
}

function raw() {
  return {
    files: [SQUARE, LARGE],
    youtube_videos: ["https://youtu.be/dQw4w9WgXcQ"],
    _accounts: [
      { customer_id: "111", name: "Northwind", currency: "GBP", time_zone: "Europe/London" },
    ],
    _files: [
      check("f-1"),
      check("f-2", {
        size_bytes: 6_348_800,
        problem: "This file is 6,200 KB. Google takes images up to 5,120 KB.",
      }),
    ],
  }
}

describe("upload media approval", () => {
  it("blocks an image Google won't take until it's cancelled, then asks for a check", () => {
    const args = parseUploadMediaArgs(raw())
    expect(uploadBlock(args)).toBe("Fix or cancel 1 File to continue.")

    const edit = editFiles(args?.files ?? [], new Set(["f-2"]), true)
    const edited = parseUploadMediaArgs(
      { ...raw(), files: edit.files },
      serializeCancelled(edit.rows)
    )
    // The cancelled row stays for Undo, and the shorter list needs the server's pin again.
    expect(edited?.files.map((file) => [file.id, file.cancelled])).toEqual([
      ["f-1", false],
      ["f-2", true],
    ])
    expect(uploadBlock(edited)).toBe(
      "Click Check Files so the changed Files are checked, then approve."
    )
  })

  it("blocks a video title YouTube won't take, and keeps the default for other videos", () => {
    const value = { ...raw(), files: [SQUARE, VIDEO], _files: [check("f-1"), VIDEO_CHECK] }
    const args = parseUploadMediaArgs(value)
    expect(uploadBlock(args)).toBeNull()

    const details = args ? editVideoText(args, "f-3", { title: "<b>Trail Fit</b>" }) : []
    expect(details).toEqual([{ file_id: "f-3", title: "<b>Trail Fit</b>" }])
    expect(uploadBlock(parseUploadMediaArgs({ ...value, video_details: details }))).toBe(
      "Fix the title of 1 video to continue."
    )
  })

  it("keeps the AI mark only for Files still in the request", () => {
    const value = { ...raw(), files: [SQUARE, VIDEO], _files: [check("f-1"), VIDEO_CHECK] }
    const args = parseUploadMediaArgs({ ...value, made_with_ai: ["f-1"] })
    if (!args) throw new Error("The arguments didn't parse")
    expect(madeWithAiIds(args, args.files, "f-3")).toEqual(["f-1", "f-3"])

    const cancelled = editFiles(args.files, new Set(["f-1"]), true)
    expect(madeWithAiIds(args, cancelled.rows)).toEqual([])
  })

  it("reads video IDs only from YouTube links", () => {
    expect(youtubeVideoId("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30")).toBe("dQw4w9WgXcQ")
    expect(youtubeVideoId("https://youtube.evil.example/watch?v=dQw4w9WgXcQ")).toBeNull()
    const args = parseUploadMediaArgs({ ...raw(), files: [SQUARE], _files: [check("f-1")] })
    expect(uploadBlock(args && { ...args, videos: ["not a video"] })).toBe(
      "Enter a YouTube link or video ID for each video."
    )
  })
})

describe("presenter", () => {
  const html = (node: ReactNode) =>
    renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement("div", null, node)
      )
    )
  const props = (activity: ToolActivity, withApproval = false) => ({
    activity,
    ...(withApproval
      ? {
          approvalDecision: {
            decision: { decision: "pending" as const, edits: {}, message: "" as const },
            error: null,
            onDecisionChange: vi.fn(),
            onRetry: vi.fn(),
            pendingCount: 1,
            submitting: false,
          },
        }
      : {}),
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "google_ads",
  })

  const approval = (args: Record<string, unknown>) =>
    html(
      googleAdsUploadMediaPresenter.render(
        props(
          {
            id: "media-1",
            kind: "approval",
            name: "google_ads_upload_media",
            status: "awaiting_approval",
            args,
          },
          true
        )
      )
    )

  it("offers the check when every image is cancelled and only videos are left", () => {
    // The server still holds the old File list, so approval waits for this check.
    expect(approval({ ...raw(), files: [] })).toContain("Check Files")
  })

  it("renders the approval and the result", () => {
    const card = approval({
      ...raw(),
      files: [SQUARE, LARGE, VIDEO],
      _files: [...raw()._files, VIDEO_CHECK],
    })
    expect(card).toContain("Square, Logo")
    expect(card).toContain("YouTube title for trail-fit-launch.mp4")

    const result = html(
      googleAdsUploadMediaPresenter.render(
        props({
          id: "media-2",
          kind: "result",
          name: "google_ads_upload_media",
          status: "completed",
          args: raw(),
          result: {
            results: [
              {
                provider_key: "google_ads",
                display_name: "Northwind",
                external_id: "111",
                status: "success",
                data: {
                  account_id: "111",
                  uploads: [
                    {
                      kind: "youtube_video",
                      name: "Trail Fit 2026",
                      outcome: "linked",
                      recovered: false,
                      asset: { asset_id: "902" },
                      video_id: "dQw4w9WgXcQ",
                      fits: [],
                    },
                    {
                      kind: "video",
                      name: "Trail Fit Launch",
                      outcome: "processing",
                      recovered: false,
                      asset: null,
                      upload_id: "555",
                      fits: [],
                      message: "Google is still processing this video.",
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("Trail Fit 2026")
    expect(result).toContain("Upload ID 555")
  })
})
