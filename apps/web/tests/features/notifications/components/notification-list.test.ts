// apps/web/tests/features/notifications/components/notification-list.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { NotificationList } from "@/features/notifications/components/notification-list"

describe("NotificationList", () => {
  it("renders typed names as text", () => {
    const html = renderToStaticMarkup(
      createElement(NotificationList, {
        notifications: [
          {
            id: "notification-1",
            notification_type: "integration_needs_reauth",
            source: "integrations",
            title: "Reconnect <img src=x onerror=alert(1)>",
            body: "<b>Agency</b>",
            payload: {},
            actions: [],
            read_at: null,
            actioned_at: null,
            action_taken: null,
            created_at: "2026-11-20T10:00:00Z",
          },
        ],
        pending: false,
        onAction: () => undefined,
        onArchive: () => undefined,
        onOpen: () => undefined,
        onToggleRead: () => undefined,
      })
    )

    expect(html).not.toContain("<img")
    expect(html).not.toContain("<b>")
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;")
  })
})
