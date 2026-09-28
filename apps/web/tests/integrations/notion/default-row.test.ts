import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it } from "vitest"

import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { notionQueryDataSourcePresenter } from "@/integrations/notion/presenters/query-data-source"
import { notionSearchPagesPresenter } from "@/integrations/notion/presenters/search-pages"
import { loadIntegrationUiModules } from "@/integrations/registry"

describe("Notion read-tool presentation", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["notion"])
  })

  it("renders success, error, truncation, and future fields without provider internals", () => {
    const activity: ToolActivity = {
      id: "notion-read-1",
      kind: "result",
      name: "notion_read_page",
      status: "completed",
      result: {
        results: [
          {
            provider_key: "notion",
            external_id: "workspace-1",
            display_name: "Operations workspace",
            status: "success",
            data: {
              reference: {
                version: 1,
                entity_kind: "notion_page",
                workspace_id: "workspace-1",
                page_id: "page-1",
                label: "Launch plan",
              },
              title: untrusted("Launch plan"),
              markdown: untrusted(
                "\\# Launch plan\nFirst line\nSecond line\n<empty-block/>\n\\#\\# Details\n\\*\\*Important\\*\\*\n\n- First item\n- Second item"
              ),
              url: "https://www.notion.so/page-1",
              source_updated_at: "2026-08-25T12:00:00Z",
              bytes_returned: 25,
              truncated: true,
              provider_truncated: true,
              unknown_block_count: 2,
              future_quality_note: "Provider supplied a partial export",
            },
            error_code: null,
            error_message: null,
          },
          {
            provider_key: "notion",
            external_id: "workspace-2",
            display_name: "Finance workspace",
            status: "error",
            data: null,
            error_code: "IntegrationPermissionError",
            error_message: "The selected Notion page could not be read.",
          },
        ],
      },
    }

    const html = render(activity)

    expect(html).toContain("The selected Notion page could not be read.")
    expect(html).toContain("<h1")
    expect(html).toContain("<h2")
    expect(html).toContain("<strong")
    expect(html).toContain("<br")
    expect(html).toContain("<ul")
    expect(html).not.toContain("\\#")
    expect(html).not.toContain("\\*")
    expect(html).not.toContain("integration_resource_id")
    expect(html).not.toContain("connection_id")
    expect(html).not.toContain("praxis_untrusted")
  })

  it("falls through to the declarative row when search or query payloads are malformed", () => {
    expect(
      notionSearchPagesPresenter.render(
        presenterProps({
          id: "bad-search",
          kind: "result",
          name: "notion_search_pages",
          status: "completed",
          result: { results: [{ data: { items: "invalid" } }] },
        })
      )
    ).toBeNull()
    expect(
      notionQueryDataSourcePresenter.render(
        presenterProps({
          id: "bad-query",
          kind: "result",
          name: "notion_query_data_source",
          status: "completed",
          result: { results: [{ data: { records: "invalid" } }] },
        })
      )
    ).toBeNull()
  })
})

function render(activity: ToolActivity) {
  const row = renderCustomToolCallRow({
    activity,
    compact: false,
    defaultOpen: true,
    live: false,
    label: "Read Notion Page",
    providerKey: "notion",
    ui: null,
  })
  expect(row).not.toBeNull()
  return renderToStaticMarkup(row)
}

function untrusted(content: string) {
  return {
    node: "praxis_untrusted",
    source_kind: "notion_page",
    source_ref: "page-1",
    content,
  }
}

function presenterProps(activity: ToolActivity) {
  return {
    activity,
    compact: false,
    defaultOpen: true,
    live: false,
    providerKey: "notion",
  }
}
