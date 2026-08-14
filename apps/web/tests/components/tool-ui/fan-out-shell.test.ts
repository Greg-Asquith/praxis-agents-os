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
            provider_key: "gmail",
            display_name: "Inbox",
            external_id: "hello@example.com",
            status: "success",
            data: { count: 2 },
          },
          {
            provider_key: "gmail",
            display_name: "Support",
            external_id: "support@example.com",
            status: "error",
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
              provider_key: "gmail",
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
          provider_key: "gmail",
          display_name: "Inbox",
          external_id: "hello@example.com",
          status: "success",
          data: { count: 2 },
        },
        {
          provider_key: "gmail",
          display_name: "Support",
          external_id: "support@example.com",
          status: "error",
          data: null,
          error_message: "Mailbox access expired.",
        },
      ],
    })
    expect(entries).not.toBeNull()
    const html = renderToStaticMarkup(
      createElement(FanOutShell, {
        contextLabel: "Mailbox",
        defaultOpen: true,
        entries: entries ?? [],
        children: (entry) => createElement("p", null, `Rendered ${entry.displayName}`),
        details: [{ label: "Search", value: "is:unread" }],
        externalLabel: "Email",
        heading: createElement("span", null, "Search Gmail"),
      })
    )

    expect(html).toContain("Search Gmail")
    expect(html).toContain("Tool succeeded on 1/2 connections")
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

  it("uses an error summary when every connection fails", () => {
    const entries = fanOutEntries({
      results: [
        {
          provider_key: "gmail",
          display_name: "Inbox",
          external_id: "hello@example.com",
          status: "error",
          data: null,
          error_message: "Mailbox access expired.",
        },
        {
          provider_key: "gmail",
          display_name: "Support",
          external_id: "support@example.com",
          status: "error",
          data: null,
          error_message: "Mailbox access expired.",
        },
      ],
    })

    const html = renderToStaticMarkup(
      createElement(FanOutShell, {
        entries: entries ?? [],
        children: () => null,
      })
    )

    expect(html).toContain("Tool failed on 2/2 connections")
    expect(html).not.toContain("successfully")
    expect(html).toContain("text-destructive")
  })

  it("formats context labels without changing the entry passed to result content", () => {
    const entries = fanOutEntries({
      results: [
        {
          provider_key: "google_ads",
          display_name: "1234567890",
          external_id: "1234567890",
          status: "success",
          data: null,
        },
      ],
    })
    const html = renderToStaticMarkup(
      createElement(FanOutShell, {
        defaultOpen: true,
        entries: entries ?? [],
        formatContextValue: (value) => value.replace(/^(\d{3})(\d{3})(\d{4})$/, "$1-$2-$3"),
        children: (entry) => createElement("p", null, `Raw ${entry.externalId}`),
      })
    )

    expect(html).toContain("123-456-7890")
    expect(html).toContain('aria-label="123-456-7890"')
    expect(html).toContain("Raw 1234567890")
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
