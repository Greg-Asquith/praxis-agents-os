import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { fanOutEntries, parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell, FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"

describe("FanOutShell", () => {
  it("rejects malformed entry envelopes so callers can use the default row", () => {
    expect(fanOutEntries(null)).toBeNull()
    expect(fanOutEntries({ results: [{ status: "success" }] })).toBeNull()
    expect(fanOutEntries({ results: "not-an-array" })).toBeNull()
  })

  it("parses successful entry data and preserves failed entries as null", () => {
    const parsed = parseFanOutData(
      {
        results: [
          {
            connection_id: "connection-1",
            display_name: "Inbox",
            external_id: "hello@example.com",
            status: "success",
            data: { count: 2 },
          },
          {
            connection_id: "connection-2",
            display_name: "Support",
            external_id: "support@example.com",
            status: "failed",
            data: { count: "not parsed" },
            error_message: "Mailbox access expired.",
          },
        ],
      },
      (value) =>
        typeof value === "object" &&
        value !== null &&
        "count" in value &&
        typeof value.count === "number"
          ? value.count
          : null
    )

    expect(parsed?.data).toEqual([2, null])
    expect(parsed?.entries).toHaveLength(2)
  })

  it("rejects malformed data from a successful entry", () => {
    expect(
      parseFanOutData(
        {
          results: [
            {
              connection_id: "connection-1",
              display_name: "Inbox",
              external_id: "hello@example.com",
              status: "success",
              data: { count: "invalid" },
            },
          ],
        },
        () => null
      )
    ).toBeNull()
  })

  it("renders mixed outcomes, entry metadata, and inline errors", () => {
    const entries = fanOutEntries({
      results: [
        {
          connection_id: "connection-1",
          display_name: "Inbox",
          external_id: "hello@example.com",
          status: "success",
          data: { count: 2 },
        },
        {
          connection_id: "connection-2",
          display_name: "Support",
          external_id: "support@example.com",
          status: "failed",
          data: null,
          error_message: "Mailbox access expired.",
        },
      ],
    })
    expect(entries).not.toBeNull()
    const html = renderToStaticMarkup(
      createElement(FanOutShell, {
        contextLabel: "Mailbox",
        entries: entries ?? [],
        children: (entry) => createElement("p", null, `Rendered ${entry.displayName}`),
        details: [{ label: "Search", value: "is:unread" }],
        externalLabel: "Email",
        heading: createElement("span", null, "Search Gmail"),
      })
    )

    expect(html).toContain("Search Gmail")
    expect(html).toContain("1 Succeeded")
    expect(html).toContain("1 Failed")
    expect(html).toContain("Inbox")
    expect(html).toContain("hello@example.com")
    expect(html).toContain("Mailbox")
    expect(html).toContain("Email")
    expect(html).toContain("is:unread")
    expect(html).toContain("Rendered Inbox")
    expect(html).toContain("Mailbox access expired.")
    expect(html).toContain("Done")
    expect(html).toContain(">Details<")
    expect(html).not.toContain("connection-1")
    expect(html).not.toContain("Connection")
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('aria-label="Collapse results"')
    expect(html.indexOf("Search Gmail")).toBeLessThan(html.indexOf("</header>"))
    expect(html.indexOf("is:unread")).toBeLessThan(html.indexOf("</header>"))
    expect(html.indexOf("Rendered Inbox")).toBeGreaterThan(html.indexOf("</header>"))
  })

  it("renders an accessible pending state", () => {
    const html = renderToStaticMarkup(
      createElement(FanOutSkeleton, { label: "Searching mailboxes…" })
    )
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("Searching mailboxes…")
    expect(html).toContain('data-slot="skeleton"')
  })
})
