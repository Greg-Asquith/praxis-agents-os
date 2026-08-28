import { describe, expect, it } from "vitest"

import {
  createIntegrationImportWorkflowState,
  integrationImportWorkflowReducer,
} from "@/features/knowledge/components/integration-import-workflow"

const preview = {
  external_id: "page-1",
  markdown_excerpt: "A bounded preview.",
  reference: { page_id: "page-1" },
  source_updated_at: null,
  title: "Team handbook",
  url: "https://example.test/page-1",
}

describe("integration import workflow", () => {
  it("moves from source selection to review with the provider title", () => {
    const state = integrationImportWorkflowReducer(createIntegrationImportWorkflowState(), {
      selection: { preview, resourceId: "resource-1" },
      type: "review",
    })

    expect(state.previewSelection).toEqual({ preview, resourceId: "resource-1" })
    expect(state.title).toBe("Team handbook")
  })

  it("returns to source selection without changing the privacy choice", () => {
    const reviewing = integrationImportWorkflowReducer(
      { ...createIntegrationImportWorkflowState(), isPrivate: false },
      {
        selection: { preview, resourceId: "resource-1" },
        type: "review",
      }
    )

    expect(integrationImportWorkflowReducer(reviewing, { type: "choose-source" })).toEqual({
      isPrivate: false,
      previewSelection: null,
      title: "",
    })
  })

  it("keeps review edits in the workflow state", () => {
    const initial = createIntegrationImportWorkflowState()
    const renamed = integrationImportWorkflowReducer(initial, {
      title: "Operations handbook",
      type: "rename",
    })
    const shared = integrationImportWorkflowReducer(renamed, {
      isPrivate: false,
      type: "set-private",
    })

    expect(shared.title).toBe("Operations handbook")
    expect(shared.isPrivate).toBe(false)
  })
})
