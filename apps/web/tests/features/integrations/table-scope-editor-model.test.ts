import { describe, expect, it } from "vitest"

import {
  addTableScopeValues,
  removeTableScopeDraft,
  type TableScopeDraft,
  tableScopeDraftError,
  tableScopeDrafts,
  tableScopeResourceIsFilterable,
  tableScopeRuleInputs,
  upsertTableScopeDraft,
} from "@/features/integrations/components/table-scope-editor-model"
import type { IntegrationResource, TableScopeRule } from "@/features/integrations/types"

const baseDraft: TableScopeDraft = {
  allowedValues: ["client-1"],
  columnName: "account_id",
  columnType: "string",
  id: "rule-1",
  resourceDisplayName: "Marketing",
  resourceId: "resource-1",
  tableExternalId: "campaign_daily",
}

const baseRule: TableScopeRule = {
  allowed_values: baseDraft.allowedValues,
  column_name: baseDraft.columnName,
  column_type: baseDraft.columnType,
  id: baseDraft.id,
  resource_display_name: baseDraft.resourceDisplayName,
  resource_external_id: "project.marketing",
  resource_id: baseDraft.resourceId,
  table_external_id: baseDraft.tableExternalId,
}

describe("table scope editor model", () => {
  it("builds neutral replace-all inputs from API rules", () => {
    const drafts = tableScopeDrafts([
      {
        allowed_values: ["client-1", "client-2"],
        column_name: "account_id",
        column_type: "string",
        id: "rule-1",
        resource_display_name: "Marketing",
        resource_external_id: "project.marketing",
        resource_id: "resource-1",
        table_external_id: "campaign_daily",
      },
    ])

    expect(tableScopeRuleInputs(drafts)).toEqual([
      {
        allowed_values: ["client-1", "client-2"],
        column_name: "account_id",
        resource_id: "resource-1",
        table_external_id: "campaign_daily",
      },
    ])
  })

  it("preserves exact values and ignores exact duplicates", () => {
    expect(addTableScopeValues(["alpha"], " beta,alpha\ngamma ")).toEqual([
      "alpha",
      " beta,alpha\ngamma ",
    ])
    expect(addTableScopeValues(["alpha"], "alpha")).toEqual(["alpha"])
    expect(addTableScopeValues(["alpha"], "")).toEqual(["alpha"])
  })

  it("reports incomplete, duplicate, empty, oversized, and non-integer states", () => {
    expect(tableScopeDraftError({ ...baseDraft, tableExternalId: "" }, [])).toBe(
      "Choose a data source, table, and column."
    )
    expect(tableScopeDraftError(baseDraft, [{ ...baseDraft, id: "other" }])).toBe(
      "This table already has a row filter."
    )
    expect(tableScopeDraftError({ ...baseDraft, allowedValues: [] }, [])).toBe(
      "Add at least one allowed value."
    )
    expect(
      tableScopeDraftError(
        { ...baseDraft, allowedValues: Array.from({ length: 201 }, (_, index) => String(index)) },
        []
      )
    ).toBe("Add no more than 200 allowed values.")
    expect(tableScopeDraftError({ ...baseDraft, allowedValues: ["x".repeat(257)] }, [])).toBe(
      "Each value must contain 1–256 characters."
    )
    expect(
      tableScopeDraftError({ ...baseDraft, allowedValues: ["1.5"], columnType: "integer" }, [])
    ).toBe("Use whole numbers for this column.")
    expect(
      tableScopeDraftError({ ...baseDraft, allowedValues: ["-10"], columnType: "integer" }, [])
    ).toBeNull()
  })

  it("builds replace-all drafts for add, edit, and remove operations", () => {
    const added = upsertTableScopeDraft([baseRule], { ...baseDraft, id: "new-1" }, null)
    expect(added.map((draft) => draft.id)).toEqual(["rule-1", "new-1"])

    const edited = upsertTableScopeDraft(
      [baseRule],
      { ...baseDraft, allowedValues: ["client-2"] },
      baseRule.id
    )
    expect(edited).toEqual([{ ...baseDraft, allowedValues: ["client-2"] }])
    expect(removeTableScopeDraft([baseRule], baseRule.id)).toEqual([])
  })

  it("requires a persisted enabled resource before filters can be added", () => {
    const resource = {
      availability: "available",
      enabled: false,
    } as IntegrationResource

    expect(tableScopeResourceIsFilterable(resource)).toBe(false)
    expect(tableScopeResourceIsFilterable({ ...resource, enabled: true })).toBe(true)
    expect(
      tableScopeResourceIsFilterable({ ...resource, availability: "removed", enabled: true })
    ).toBe(false)
  })
})
