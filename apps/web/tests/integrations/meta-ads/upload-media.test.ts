import { createElement, type ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { ToolActivity } from "@/integrations/contract"
import {
  parseMediaUploadArgs,
  parseMediaUploadResult,
} from "@/integrations/meta_ads/lib/media-upload"
import { metaAdsUploadMediaPresenter } from "@/integrations/meta_ads/presenters/upload-media"

const hero = { version: 1, entity_kind: "file", entity_id: "f-1", label: "hero.png" }
const launch = { version: 1, entity_kind: "file", entity_id: "f-2", label: "launch.mp4" }
const pin = { revision_id: "r-1", content_hash: "a".repeat(64) }
const pins = [
  { ...pin, file_id: "f-1", name: "hero.png", media_type: "image", size_bytes: 2048 },
  { ...pin, file_id: "f-2", name: "launch.mp4", media_type: "video", size_bytes: 4096 },
]
const APPROVE_DISABLED = /<button[^>]*\sdisabled=""[^>]*>Approve/

describe("Meta Ads media upload review", () => {
  it("needs a check whenever the Files differ from the ones the server pinned", () => {
    const review = (files: unknown[]) =>
      parseMediaUploadArgs({ files, _files: pins, _account_name: "Acme UK" })?.needsReview

    expect(review([hero, launch])).toBe(false)
    expect(review([launch, hero])).toBe(true)
    expect(review([hero])).toBe(true)
    expect(parseMediaUploadArgs({ files: [hero] })?.needsReview).toBe(true)
  })

  it("needs a check when a pin lacks the reviewed revision or a File isn't a File", () => {
    const unpinned = pins.map(({ revision_id: _revision, ...rest }) => rest)
    const args = { files: [hero, launch], _account_name: "Acme UK" }

    expect(parseMediaUploadArgs({ ...args, _files: unpinned })?.needsReview).toBe(true)
    const page = { ...hero, entity_kind: "meta_ads_page" }
    expect(parseMediaUploadArgs({ ...args, files: [page, launch], _files: pins })).toBeNull()
  })

  it("blocks approval until an edited File list is checked", () => {
    const args = { files: [hero, launch], _files: pins, _account_name: "Acme UK" }
    const ready = render(approval(args))
    expect(ready).not.toMatch(APPROVE_DISABLED)
    expect(ready).toContain("1 image and 1 video to Acme UK")

    expect(render(approval({ ...args, files: [hero] }))).toMatch(APPROVE_DISABLED)
  })

  it("keeps the returned media ID only when it matches the File's media type", () => {
    const result = parseMediaUploadResult({
      account_id: "111",
      uploads: [
        upload("f-1", "hero.png", "image", "uploaded", { media_type: "image", image_hash: "abc" }),
        upload("f-2", "launch.mp4", "video", "processing", { media_type: "video", video_id: "9" }),
        upload("f-3", "clip.mp4", "video", "uploaded", { media_type: "image", image_hash: "abc" }),
      ],
    })

    expect(result?.uploads.map((item) => item.mediaId)).toEqual(["abc", "9", null])
  })

  it("shows each File's outcome when only some uploaded", () => {
    const html = render(
      metaAdsUploadMediaPresenter.render(
        props({
          id: "r1",
          kind: "result",
          name: "meta_ads_upload_media",
          status: "completed",
          args: { files: [hero, launch] },
          result: {
            results: [
              {
                provider_key: "meta_ads",
                external_id: "111",
                display_name: "Acme UK",
                status: "success",
                error_code: null,
                error_message: null,
                data: {
                  account_id: "111",
                  uploads: [
                    upload("f-1", "hero.png", "image", "uploaded", { image_hash: "abc" }),
                    {
                      ...upload("f-2", "launch.mp4", "video", "failed", null),
                      error_code: "source_changed",
                      message: "The File changed after it was approved.",
                    },
                  ],
                },
              },
            ],
          },
        })
      )
    )
    expect(html).toContain("Uploaded")
    expect(html).toContain("The File changed after it was approved.")
  })
})

function upload(
  fileId: string,
  name: string,
  mediaType: string,
  outcome: string,
  media: Record<string, unknown> | null
) {
  return {
    file_id: fileId,
    revision_id: "r-1",
    name,
    media_type: mediaType,
    outcome,
    recovered: false,
    media,
    error_code: null,
    message: null,
  }
}

function approval(args: Record<string, unknown>) {
  return metaAdsUploadMediaPresenter.render(
    props(
      {
        id: "a1",
        kind: "approval",
        name: "meta_ads_upload_media",
        status: "awaiting_approval",
        args,
      },
      true
    )
  )
}

function props(activity: ToolActivity, withApproval = false) {
  return {
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
    providerKey: "meta_ads",
  }
}

function render(node: ReactNode) {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement("div", null, node)
    )
  )
}
