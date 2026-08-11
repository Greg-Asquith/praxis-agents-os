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
                keyword_outcomes: [
                  {
                    text: "free",
                    match_type: "EXACT",
                    outcome: "added",
                    external_ref: "customers/123/campaignCriteria/10~1",
                  },
                  {
                    text: "jobs",
                    match_type: "PHRASE",
                    outcome: "failed",
                    error_code: "INVALID_KEYWORD_TEXT",
                  },
                ],
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
    expect(html).toContain("Keyword Outcomes")
    expect(html).toContain("Match Type")
    expect(html).toContain("External Ref")
    expect(html).toContain("Error Code")
    expect(html).toContain("free")
    expect(html).toContain("jobs")
    expect(html).toContain("INVALID_KEYWORD…")
    expect(html).toContain("sm:col-span-2")
    expect(html).toContain('aria-label="Structured details"')
    expect(html).not.toContain('class="divide-y"')
    expect(html).not.toContain("max-h-64")
    expect(html.indexOf(">Text</th>")).toBeLessThan(html.indexOf(">Match Type</th>"))
    expect(html.indexOf(">Match Type</th>")).toBeLessThan(html.indexOf(">Outcome</th>"))
    expect(html.indexOf(">Outcome</th>")).toBeLessThan(html.indexOf(">External Ref</th>"))
    expect(html).toContain(">added</span>")
    expect(html).toContain("brand")
    expect(html).toContain("customers/123/sharedCriteria/50~1")
  })

  it("preserves record field order without provider-specific column rules", () => {
    const html = renderToStaticMarkup(
      createElement(IntegrationOperationDetail, {
        value: {
          schema_version: 1,
          target: {
            entity_type: "generic_resource",
            external_id: "resource-1",
            display_name: null,
            integration_resource_id: "resource-1",
            attributes: {},
          },
          changes: [
            {
              action: "update",
              entity_type: "generic_record",
              external_ref: null,
              fields: {
                rows: [
                  {
                    zeta_field: "123456789012345",
                    text: "1234567890123456",
                    alpha_field: "third",
                  },
                ],
              },
            },
          ],
          counts: { applied: 1, skipped: 0, failed: 0 },
        },
      })
    )

    expect(html.indexOf(">Zeta Field</th>")).toBeLessThan(html.indexOf(">Text</th>"))
    expect(html.indexOf(">Text</th>")).toBeLessThan(html.indexOf(">Alpha Field</th>"))
    expect(html).toContain(">123456789012345</span>")
    expect(html).toContain(">123456789012345…</span>")
    expect(html).toContain('data-slot="tooltip-trigger"')
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
