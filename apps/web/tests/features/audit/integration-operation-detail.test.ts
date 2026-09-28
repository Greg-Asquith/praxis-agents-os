import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { paginateItems } from "@/components/ui/pagination-controls"
import { IntegrationOperationDetail } from "@/features/audit/components/integration-operation-detail"

const AUDIT_DETAIL_PAGE_SIZE = 25

describe("IntegrationOperationDetail", () => {
  it("fails closed for malformed counts and old versioned shapes", () => {
    const malformed = { ...terminalDetail(), intent_counts: { applied: 99 } }

    expect(
      renderToStaticMarkup(
        createElement(IntegrationOperationDetail, { eventId: "event-1", value: malformed })
      )
    ).toBe("")
    expect(
      renderToStaticMarkup(
        createElement(IntegrationOperationDetail, {
          value: { schema_version: 1, target: {}, changes: [], counts: {} },
          eventId: "event-1",
        })
      )
    ).toBe("")
  })

  it.each([0, 26])("bounds an initial collection of %i rows", (size) => {
    const rows = Array.from({ length: size }, (_, index) => index + 1)
    const page = paginateItems(rows, 0, AUDIT_DETAIL_PAGE_SIZE)

    expect(page.items).toHaveLength(Math.min(size, AUDIT_DETAIL_PAGE_SIZE))
    expect(page.offset).toBe(0)
  })

  it("keeps the last persisted row reachable and clamps stale offsets", () => {
    const rows = Array.from({ length: 2_500 }, (_, index) => `row-${String(index + 1)}`)

    expect(paginateItems(rows, 2_475, AUDIT_DETAIL_PAGE_SIZE)).toEqual({
      items: rows.slice(2_475),
      offset: 2_475,
    })
    expect(paginateItems(rows, 99_999, AUDIT_DETAIL_PAGE_SIZE)).toEqual({
      items: rows.slice(2_475),
      offset: 2_475,
    })
  })
})

function pendingDetail() {
  return {
    phase: "pending",
    target: {
      entity_type: "google_ads_shared_set",
      external_id: "50",
      display_name: "Brand Protection",
      integration_resource_id: "resource-1",
      attributes: { member_count: 12 },
    },
    intent_groups: [
      {
        key: "shared-set:50:add-keywords",
        action: "add",
        entity_type: "negative_keyword",
        external_id: "50",
        display_name: "Brand Protection",
        fields: {},
        items: [{ fields: { text: "Brand Term", match_type: "EXACT" } }],
      },
    ],
  }
}

function terminalDetail() {
  return {
    phase: "terminal",
    target: pendingDetail().target,
    intent_groups: [
      {
        key: "shared-set:50:remove-keywords",
        action: "remove",
        entity_type: "negative_keyword",
        external_id: "50",
        display_name: "Brand Protection",
        fields: {},
        items: [
          { fields: { text: "Brand Term", match_type: "EXACT" } },
          { fields: { text: "jobs", match_type: "ANY" } },
        ],
      },
    ],
    outcome_groups: [
      {
        key: "shared-set:50:remove-keywords",
        outcomes: [
          { intent_index: 0, status: "skipped", fields: { reason: "not_found" }, effects: [] },
          {
            intent_index: 1,
            status: "failed",
            fields: {},
            effects: [
              {
                status: "applied",
                fields: { text: "jobs", match_type: "EXACT" },
                external_ref: "criteria/1",
                error_code: null,
              },
              {
                status: "failed",
                fields: { text: "jobs", match_type: "PHRASE" },
                external_ref: null,
                error_code: "NOT_REMOVED",
              },
            ],
          },
        ],
      },
    ],
    intent_counts: { applied: 0, skipped: 1, failed: 1, unverified: 0 },
    effect_counts: { applied: 1, skipped: 0, failed: 1, unverified: 0 },
  }
}
