// apps/web/tests/features/conversations/components/tools/web/check-urls-result.test.ts

import { describe, expect, it } from "vitest"

import { checkUrlsResult } from "@/features/conversations/components/tools/web/check-urls-result"

function node(content: string) {
  return { node: "praxis_untrusted", source_kind: "web_fetch", source_ref: "ref", content }
}

function row(url: string, fields: Record<string, unknown> = {}) {
  return {
    requested_url: url,
    status: 200,
    redirects: [],
    final_url: node(url),
    content_type: node("text/html"),
    content_length: null,
    headers: {},
    time_to_first_byte_ms: 40,
    blocked_by_site: false,
    error_class: null,
    page: null,
    ...fields,
  }
}

const HOP = { url: node("https://a.example/old"), status: 301, location: node("/new") }

describe("checkUrlsResult", () => {
  it("sorts rows into outcomes and keeps a row whose final URL isn't http(s)", () => {
    const result = checkUrlsResult({
      user_agent: "praxis",
      checked_at: "2026-11-23T10:00:00+00:00",
      checked: 5,
      not_checked: 1,
      rows: [
        row("https://a.example/ok"),
        row("https://a.example/old", { redirects: [HOP], final_url: node("javascript:x") }),
        row("https://a.example/gone", { redirects: [HOP], status: 404 }),
        row("not a url", { status: null, error_class: "invalid_url" }),
        row("https://a.example/waf", { status: 403, blocked_by_site: true }),
        row("https://a.example/late", { status: null, error_class: "not_checked" }),
      ],
    })

    expect(result?.rows.map((entry) => entry.outcome)).toEqual([
      "ok",
      "redirected",
      "broken",
      "broken",
      "blocked",
      "not_checked",
    ])
    expect(result?.rows[1]?.finalUrl).toBeNull()
  })
})
