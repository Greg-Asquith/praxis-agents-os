import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ClassifiersTable } from "@/features/classifiers/components/classifiers-table"
import type { Classifier } from "@/features/classifiers/types"
import type { ModelCatalogResponse } from "@/features/models/types"

const classifier: Classifier = {
  created_at: "2026-08-18T09:00:00Z",
  created_by: "user-1",
  description: "Route customer messages by primary intent.",
  display_name: "Complaint triage",
  id: "classifier-1",
  instructions: null,
  is_active: true,
  labels: [
    { description: "Needs recovery.", label: "Complaint" },
    { description: null, label: "Other" },
  ],
  model: "gpt-5.6-luna",
  model_provider: "openai",
  name: "complaint_triage",
  updated_at: "2026-08-18T10:00:00Z",
  workspace_id: "workspace-1",
}

const modelCatalog: ModelCatalogResponse = {
  defaults: { agent_model: null },
  models: [
    {
      context_window: 100_000,
      default_settings: {},
      display_name: "GPT 5.6 Luna",
      id: "openai:gpt-5.6-luna",
      model: "gpt-5.6-luna",
      provider: "openai",
      supports_structured_output: true,
      supports_thinking: false,
      supports_tools: true,
      supports_vision: false,
    },
  ],
  providers: [{ configured: true, display_name: "OpenAI", model_count: 1, provider: "openai" }],
}

describe("ClassifiersTable", () => {
  it("renders the operator name, tool name, category count, model, state, and actions", () => {
    const html = render([classifier])

    expect(html).toContain("Complaint triage")
    expect(html).toContain("classifier_complaint_triage")
    expect(html).toContain("2 categories")
    expect(html).toContain("OpenAI · GPT 5.6 Luna")
    expect(html).toContain("Active")
    expect(html).toContain('aria-label="Edit Complaint triage"')
    expect(html).toContain('aria-label="Delete Complaint triage"')
  })

  it("renders a focused empty state with a creation action", () => {
    const html = render([])

    expect(html).toContain("No classifiers yet")
    expect(html).toContain("New Classifier")
    expect(html).not.toContain("<table")
  })
})

function render(classifiers: Classifier[]) {
  return renderToStaticMarkup(
    createElement(ClassifiersTable, {
      classifiers,
      modelCatalog,
      onCreate: vi.fn(),
      onDelete: vi.fn(),
      onEdit: vi.fn(),
    })
  )
}
