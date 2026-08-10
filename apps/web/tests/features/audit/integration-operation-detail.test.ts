import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { IntegrationOperationDetail } from "@/features/audit/components/integration-operation-detail"
import { AuditEventFields } from "@/features/audit/components/audit-event-detail"
import type { AuditEvent } from "@/features/audit/types"

describe("IntegrationOperationDetail", () => {
  it("renders provider-neutral targets, outcome counts, and full applied change fields", () => {
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, {
        value: {
          schema_version: 1,
          target: {
            entity_type: "google_ads_shared_set",
            external_id: "50",
            display_name: "Brand Protection",
            integration_resource_id: "resource-1",
            attributes: { member_count: 12 },
          },
          changes: [
            {
              action: "add",
              entity_type: "negative_keyword",
              external_ref: "customers/123/sharedCriteria/50~1",
              fields: {
                text: "Brand Term",
                match_type: "EXACT",
                settings: { close_variants: false, labels: ["brand", "reviewed"] },
              },
            },
          ],
          counts: { applied: 1, skipped: 2, failed: 3 },
        },
      })
    )

    expect(html).toContain('aria-label="Integration operation outcome"')
    expect(html).toContain("Brand Protection")
    expect(html).toContain("Google Ads Shared Set")
    expect(html).toContain("Member Count")
    expect(html).toContain("1 applied")
    expect(html).toContain("2 skipped")
    expect(html).toContain("3 failed")
    expect(html).toContain("Brand Term")
    expect(html).toContain("EXACT")
    expect(html).toContain("close_variants")
    expect(html).toContain("brand")
    expect(html).toContain("customers/123/sharedCriteria/50~1")
  })

  it("fails closed for malformed operation detail", () => {
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, {
        value: { schema_version: 1, target: {}, changes: [], counts: {} },
      })
    )

    expect(html).toBe("")
  })

  it("renders the normal audit fallback when rich detail is malformed", () => {
    const html = renderToStaticMarkup(
      createElement(AuditEventFields, {
        event: auditEvent({ operation_detail: { schema_version: 99 } }),
        toolLabelFor: (toolName: string) => toolName,
      })
    )

    expect(html).toContain("Persisted operation summary")
    expect(html).toContain("Integration Resource resource-1")
  })

  it("renders serialized persisted operation detail instead of the generic summary", () => {
    const html = renderToStaticMarkup(
      createElement(AuditEventFields, {
        event: auditEvent({
          operation_detail: {
            schema_version: 1,
            target: {
              entity_type: "google_ads_shared_set",
              external_id: "50",
              display_name: "Brand Protection",
              integration_resource_id: "resource-1",
              attributes: {},
            },
            changes: [
              {
                action: "add",
                entity_type: "negative_keyword",
                external_ref: "customers/123/sharedCriteria/50~1",
                fields: { text: "Brand Term", match_type: "EXACT" },
              },
            ],
            counts: { applied: 1, skipped: 0, failed: 0 },
          },
        }),
        toolLabelFor: (toolName: string) => toolName,
      })
    )

    expect(html).toContain("Brand Protection")
    expect(html).toContain("Brand Term")
    expect(html).toContain("Persisted operation summary")
  })
})

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
