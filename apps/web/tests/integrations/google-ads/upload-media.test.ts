// apps/web/tests/integrations/google-ads/upload-media.test.ts

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  editImages,
  parseUploadMediaArgs,
  serializeCancelled,
  uploadBlock,
  youtubeVideoId,
} from "@/integrations/google_ads/lib/upload-media"
import { googleAdsUploadMediaPresenter } from "@/integrations/google_ads/presenters/upload-media"

const SQUARE = { entity_kind: "file", entity_id: "f-1", label: "logo-mark.png" }
const LARGE = { entity_kind: "file", entity_id: "f-2", label: "trail-hero-wide.png" }

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
    _account_name: "Northwind",
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
    expect(uploadBlock(args)).toBe("Fix or cancel 1 image to continue.")

    const edit = editImages(args?.images ?? [], new Set(["f-2"]), true)
    const edited = parseUploadMediaArgs(
      { ...raw(), files: edit.files },
      serializeCancelled(edit.rows)
    )
    // The cancelled row stays for Undo, and the shorter list needs the server's pin again.
    expect(edited?.images.map((image) => [image.id, image.cancelled])).toEqual([
      ["f-1", false],
      ["f-2", true],
    ])
    expect(uploadBlock(edited)).toBe(
      "Click Check Files so the changed Files are checked, then approve."
    )
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

  it("renders the approval and the result", () => {
    const approval = html(
      googleAdsUploadMediaPresenter.render(
        props(
          {
            id: "media-1",
            kind: "approval",
            name: "google_ads_upload_media",
            status: "awaiting_approval",
            args: raw(),
          },
          true
        )
      )
    )
    expect(approval).toContain("Square, Logo")

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
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(result).toContain("Trail Fit 2026")
  })
})
