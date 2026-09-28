import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { fanOutEntries, parseFanOutData } from "@/components/tool-ui/fan-out"
import { FanOutShell } from "@/components/tool-ui/fan-out-shell"

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

  it("keeps unverified entries and an all-unconfirmed summary distinct from failures", () => {
    const entries = fanOutEntries({
      results: ["One", "Two"].map((name) => ({
        provider_key: "outlook_mail",
        display_name: name,
        external_id: name,
        status: "error",
        data: null,
        error_code: "unverified_mutation",
      })),
    })
    const html = renderToStaticMarkup(
      createElement(FanOutShell, {
        entries: entries ?? [],
        children: () => null,
      })
    )
    expect(html).toContain("Success confirmed on 0/2 connections")
    expect(html.match(/>Unconfirmed</g)).toHaveLength(2)
    expect(html).not.toContain("Tool failed")
    expect(html).not.toContain(">Failed<")
  })
})
