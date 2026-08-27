import { renderToStaticMarkup } from "react-dom/server"
import { beforeAll, describe, expect, it } from "vitest"

import { resolveToolField } from "@/components/tool-ui/field-resolution"
import { renderCustomToolCallRow } from "@/features/conversations/components/tool-call-row-registry"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { notionQueryDataSourcePresenter } from "@/integrations/notion/presenters/query-data-source"
import { notionSearchPagesPresenter } from "@/integrations/notion/presenters/search-pages"
import { loadIntegrationUiModules } from "@/integrations/registry"
import { formatDateTime } from "@/lib/format"

describe("Notion read-tool presentation", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["notion"])
  })

  it("documents why the scalar default list field cannot preserve structured fan-out", () => {
    expect(
      resolveToolField({ key: "results", label: "Workspaces", format: "list" }, [
        { status: "success", data: { title: "Launch plan" } },
      ])
    ).toBeNull()
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

    expect(html).toContain("Launch plan")
    expect(html).toContain("64 KiB limit reached")
    expect(html).toContain("Notion result incomplete")
    expect(html).toContain(formatDateTime("2026-08-25T12:00:00Z"))
    expect(html).toContain("Unknown blocks")
    expect(html).toContain("The selected Notion page could not be read.")
    expect(html).toContain("Future quality note")
    expect(html).toContain("Provider supplied a partial export")
    expect(html).toContain("<h1")
    expect(html).toContain("<h2")
    expect(html).toContain("<strong")
    expect(html).toContain("<br")
    expect(html).toContain("<ul")
    expect(html).not.toContain("\\#")
    expect(html).not.toContain("\\*")
    expect(html).toContain("Tool succeeded")
    expect(html).not.toContain("integration_resource_id")
    expect(html).not.toContain("connection_id")
    expect(html).not.toContain("praxis_untrusted")
  })

  it("renders search coverage, formatted freshness, pagination state, and future fields", () => {
    const html = render({
      id: "notion-search-1",
      kind: "result",
      name: "notion_search_pages",
      status: "completed",
      result: {
        results: [
          {
            provider_key: "notion",
            external_id: "workspace-1",
            display_name: "Operations workspace",
            status: "success",
            data: {
              items: [
                {
                  kind: "data_source",
                  title: untrusted("Launch tracker"),
                  url: "https://www.notion.so/source-1",
                  last_edited_time: "2026-08-25T11:00:00Z",
                  reference: {
                    version: 1,
                    entity_kind: "notion_data_source",
                    workspace_id: "workspace-1",
                    data_source_id: "source-1",
                    label: "Launch tracker",
                  },
                  future_quality_note: "Synced from a linked database",
                },
              ],
              count: 1,
              has_more: true,
              next_cursor: "cursor-2",
              coverage_note: "Search matches titles only and can be incomplete or delayed.",
            },
            error_code: null,
            error_message: null,
          },
        ],
      },
    })

    expect(html).toContain("Launch tracker")
    expect(html).toContain("Data source")
    expect(html).toContain(formatDateTime("2026-08-25T11:00:00Z"))
    expect(html).toContain("More title matches are available.")
    expect(html).toContain("Future quality note")
    expect(html).toContain("Synced from a linked database")
  })

  it("renders queried records as a paginated, exportable table without losing metadata", () => {
    const records = Array.from({ length: 26 }, (_, index) => ({
      reference: {
        version: 1,
        entity_kind: "notion_page",
        workspace_id: "workspace-1",
        page_id: `page-${String(index + 1)}`,
        label: `Launch item ${String(index + 1)}`,
      },
      title: untrusted(`Launch item ${String(index + 1)}`),
      url: `https://www.notion.so/page-${String(index + 1)}`,
      last_edited_time: "2026-08-25T10:00:00Z",
      properties: {
        "6 Months": index === 0 ? { type: "formula" } : 6,
        Archived: index === 0,
        Due: { start: untrusted("2023-10-13") },
        Estimate: index + 1,
        Priority: untrusted(index === 0 ? "High" : "Normal"),
        Related: { type: "relation" },
        Tags: [untrusted("Launch"), untrusted("P1")],
        "Unsupported formula": { unsupported_formula_type: "future_type" },
      },
      properties_truncated: index === 0,
      ...(index === 0 ? { future_quality_note: "Provider supplied a partial row" } : {}),
    }))
    const html = render({
      id: "notion-query-1",
      kind: "result",
      name: "notion_query_data_source",
      status: "completed",
      result: {
        results: [
          {
            provider_key: "notion",
            external_id: "workspace-1",
            display_name: "Operations workspace",
            status: "success",
            data: {
              records,
              count: records.length,
              has_more: true,
              next_cursor: "cursor-2",
              incomplete: true,
            },
            error_code: null,
            error_message: null,
          },
        ],
      },
    })

    expect(html).toContain("Query incomplete")
    expect(html).toContain("Some record properties omitted")
    expect(html).toContain("More records available")
    expect(html).toContain("Last edited")
    expect(html).toContain(formatDateTime("2026-08-25T10:00:00Z"))
    expect(html).toContain("Estimate")
    expect(html).toContain("Unavailable")
    expect(html).toContain(">Yes<")
    expect(html).toContain(">No<")
    expect(html).toContain(">2023-10-13<")
    expect(html).toContain("Priority")
    expect(html).toContain("Launch, P1")
    expect(html).toContain("Future quality note")
    expect(html).toContain("Provider supplied a partial row")
    expect(html).toContain("Download Report CSV")
    expect(html).toContain("Showing 1-25 of 26")
    expect(html).not.toContain("praxis_untrusted")
    expect(html).not.toContain("Type: formula")
    expect(html).not.toContain("Type: relation")
    expect(html).not.toContain("Unsupported formula type")
    expect(html).not.toContain("Start: 2023-10-13")
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
