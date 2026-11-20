// apps/web/tests/features/notifications/notification-content.test.ts

import { describe, expect, it } from "vitest"

import {
  notificationActions,
  notificationTarget,
} from "@/features/notifications/notification-content"
import type { AppNotification } from "@/features/notifications/types"

function notification(overrides: Partial<AppNotification>): AppNotification {
  return {
    id: "notification-1",
    notification_type: "job_failed",
    source: "jobs",
    title: "Background job failed",
    body: null,
    payload: {},
    actions: [],
    read_at: null,
    actioned_at: null,
    action_taken: null,
    created_at: "2026-11-20T10:00:00Z",
    ...overrides,
  }
}

describe("notification content", () => {
  it("links only to targets the payload names with a usable value", () => {
    expect(
      notificationTarget(
        notification({
          notification_type: "integration_needs_reauth",
          payload: { provider_key: "google_ads", connection_id: "c-1" },
        })
      )
    ).toEqual({ kind: "integration", providerKey: "google_ads" })
    expect(
      notificationTarget(notification({ payload: { conversation_id: "conversation-1" } }))
    ).toEqual({ kind: "conversation", conversationId: "conversation-1" })
    expect(notificationTarget(notification({ payload: { provider_key: "google_ads" } }))).toBe(null)
    expect(notificationTarget(notification({ payload: "not an object" }))).toBe(null)
  })

  it("offers well-formed actions until one has been taken", () => {
    const actions = [{ key: "review" }, { label: "No key" }, "review"]

    expect(notificationActions(notification({ actions }))).toEqual([
      { key: "review", label: "Review" },
    ])
    expect(
      notificationActions(notification({ actions, actioned_at: "2026-11-20T11:00:00Z" }))
    ).toEqual([])
  })
})
