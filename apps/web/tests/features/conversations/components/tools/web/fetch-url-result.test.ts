// apps/web/tests/features/conversations/components/tools/web/fetch-url-result.test.ts

import { describe, expect, it } from "vitest"

import { fetchUrlResult } from "@/features/conversations/components/tools/web/fetch-url-result"

function node(content: string) {
  return { node: "praxis_untrusted", source_kind: "web_fetch", source_ref: "ref", content }
}

function result(finalUrl: string) {
  return {
    provider: "http",
    requested_url: "https://shop.example/old",
    final_url: node(finalUrl),
    status: 404,
    redirects: [{ url: node("https://shop.example/old"), status: 301, location: node(finalUrl) }],
    blocked_by_site: false,
    user_agent: "praxis",
    content_type: node("text/html"),
    format: "html",
    title: node("Not Found"),
    fetched_at: "2026-11-23T10:00:00+00:00",
    bytes: 120,
    truncated: false,
    content: node("<h1>Not Found</h1>"),
    note: null,
    file: null,
    knowledge_base_document: null,
  }
}

describe("fetchUrlResult", () => {
  it("reads server strings from untrusted nodes and refuses a final URL that isn't http(s)", () => {
    expect(fetchUrlResult(result("https://shop.example/new"))).toMatchObject({
      content: "<h1>Not Found</h1>",
      finalUrl: "https://shop.example/new",
      redirects: [{ location: "https://shop.example/new", status: 301 }],
      status: 404,
      title: "Not Found",
    })
    expect(fetchUrlResult(result("javascript:alert(1)"))).toBeNull()
  })
})
