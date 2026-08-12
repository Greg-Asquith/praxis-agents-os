import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { paginateItems } from "@/components/ui/pagination-controls"
import { AuditEventFields } from "@/features/audit/components/audit-event-detail"
import { IntegrationOperationDetail } from "@/features/audit/components/integration-operation-detail"
import type { AuditEvent } from "@/features/audit/types"

const AUDIT_DETAIL_PAGE_SIZE = 25

describe("IntegrationOperationDetail", () => {
  it("renders pending intent without claiming an outcome", () => {
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, { eventId: "event-1", value: pendingDetail() })
    )

    expect(html).toContain('aria-label="Integration operation evidence"')
    expect(html).toContain("Waiting to record the provider outcome")
    expect(html).toContain("No outcome is claimed yet")
    expect(html).toContain("Brand Protection")
    expect(html).toContain("Requested changes")
    expect(html).toContain("Brand Term")
    expect(html).not.toContain("completed")
    expect(html).not.toContain("applied")
  })

  it("renders independently counted terminal intent and concrete effects", () => {
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, { eventId: "event-1", value: terminalDetail() })
    )

    expect(html).toContain("Some requested changes failed")
    expect(html).toContain("1 Skipped")
    expect(html).toContain("1 Failed")
    expect(html).not.toContain("Requests")
    expect(html).not.toContain("Provider effects")
    expect(html).toContain("2 concrete effects")
    expect(html).toContain("Not Found")
    expect(html).not.toContain("not_found")
    expect(html).toContain("criteria/1")
    expect(html).toContain("NOT_REMOVED")
    expect(html).toContain("Match Type")
    expect(html).toContain("PHRASE")
    expect(html).toContain('aria-label="Structured details"')
  })

  it("renders unverified evidence explicitly", () => {
    const detail = terminalDetail()
    const terminal = {
      ...detail,
      outcome_groups: [
        {
          key: "shared-set:50:remove-keywords",
          outcomes: [
            detail.outcome_groups[0]?.outcomes[0],
            {
              intent_index: 1,
              status: "unverified",
              fields: {},
              effects: [
                {
                  status: "unverified",
                  fields: { text: "jobs", match_type: "ANY" },
                  external_ref: null,
                  error_code: "UNKNOWN_RESULT",
                },
              ],
            },
          ],
        },
      ],
      intent_counts: { applied: 0, skipped: 1, failed: 0, unverified: 1 },
      effect_counts: { applied: 0, skipped: 0, failed: 0, unverified: 1 },
    }
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, { eventId: "event-1", value: terminal })
    )

    expect(html).toContain("could not be verified")
    expect(html).toContain("Unverified")
    expect(html).toContain("UNKNOWN_RESULT")
  })

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

  it.each([0, 1, 25, 26, 2_500])("bounds an initial collection of %i rows", (size) => {
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

  it("renders only the first outcome and nested-record pages with accessible controls", () => {
    const detail = largePendingDetail(2_500)
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, { eventId: "event-large", value: detail })
    )

    expect(html.match(/>Item \d+</g)).toHaveLength(25)
    expect(html).toContain("Item 25")
    expect(html).not.toContain("Item 26")
    expect(html).toContain('aria-label="Requested changes pagination"')
    expect(html).toContain('aria-label="Structured details pagination"')
    expect(html).toContain('role="status"')
    expect(html).toContain("Showing 1-25 of 2500")
    expect(html).toContain('type="button"')
    expect(html).toContain("record-25")
    expect(html).not.toContain("record-26")
  })

  it("keys pagination state to the audit event", () => {
    const first = IntegrationOperationDetail({ eventId: "event-1", value: pendingDetail() })
    const second = IntegrationOperationDetail({ eventId: "event-2", value: pendingDetail() })

    expect(first?.key).toBe("event-1")
    expect(second?.key).toBe("event-2")
  })

  it("uses the normal audit fallback for data outside the one current contract", () => {
    const html = renderToStaticMarkup(
      createElement(AuditEventFields, {
        event: auditEvent({ operation_detail: { schema_version: 1 } }),
        toolLabelFor: (toolName: string) => toolName,
      })
    )

    expect(html).toContain("Persisted operation summary")
    expect(html).toContain("Integration Resource resource-1")
  })

  it("uses the current contract instead of the generic summary", () => {
    const html = renderToStaticMarkup(
      createElement(AuditEventFields, {
        event: auditEvent({ operation_detail: terminalDetail() }),
        toolLabelFor: (toolName: string) => toolName,
      })
    )

    expect(html).toContain("Brand Protection")
    expect(html).toContain("Brand Term")
    expect(html).toContain("Persisted operation summary")
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

function largePendingDetail(size: number) {
  return {
    ...pendingDetail(),
    target: {
      ...pendingDetail().target,
      attributes: {
        records: Array.from({ length: size }, (_, index) => ({
          name: `record-${String(index + 1)}`,
        })),
      },
    },
    intent_groups: [
      {
        ...pendingDetail().intent_groups[0],
        items: Array.from({ length: size }, (_, index) => ({
          fields: { text: `keyword-${String(index + 1)}`, match_type: "EXACT" },
        })),
      },
    ],
  }
}

function auditEvent(details: Record<string, unknown>): AuditEvent {
  return {
    id: "event-1",
    detail_event_id: "event-1",
    workspace_id: "workspace-1",
    occurred_at: "2026-08-10T10:06:00Z",
    action: "execute",
    resource_type: "integration_resource",
    resource_id: "resource-1",
    status: "success",
    summary: "Persisted operation summary",
    tool_name: "google_ads_add_negative_keywords",
    tool_provider: "google_ads",
    actor_type: "agent",
    actor_id: "agent-1",
    actor_user_id: null,
    actor_display: "Ads operator",
    requested_by_user_id: "user-1",
    details,
    request_id: null,
    ip_address: null,
    user_agent: null,
    created_at: "2026-08-10T10:06:00Z",
  }
}
