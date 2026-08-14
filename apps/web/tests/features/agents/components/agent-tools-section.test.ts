import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import {
  AgentToolsSection,
  CodeModeInfoBody,
} from "@/features/agents/components/agent-tools-section"
import { initialAgentFormState } from "@/features/agents/components/agent-form-model"
import type { ToolCatalogEntry } from "@/features/tools/types"

const readFile: ToolCatalogEntry = {
  default_policy: "auto",
  defer_loading: false,
  description: "Read workspace files.",
  effect: "read",
  effect_scope: "internal",
  egress: "none",
  kind: "function",
  label: "Read file",
  name: "read_file",
  provider: "core",
  supported_policies: ["auto", "approval"],
}

const runWorkflow: ToolCatalogEntry = {
  ...readFile,
  description: "Internal workflow tool.",
  label: "Run workflow",
  name: "run_workflow",
}

describe("AgentToolsSection", () => {
  it("renders code mode as an off-by-default section switch above the tool list", () => {
    const html = renderSection([readFile])

    expect(html).toContain("Let this agent combine tools in one workflow")
    expect(html).toContain('aria-label="About combining tools"')
    expect(html).toContain('role="switch"')
    expect(html).toContain('aria-checked="false"')
    expect(html.indexOf('role="switch"')).toBeLessThan(html.indexOf("Choose tools"))
  })

  it("never renders run_workflow as a configurable tool row", () => {
    const html = renderSection([readFile, runWorkflow])

    expect(html).toContain("Core")
    expect(html).not.toContain("Run workflow")
    expect(html).not.toContain("Internal workflow tool")
    expect(html).toContain("1 tool")
  })

  it("explains when to enable or leave code mode off", () => {
    const html = renderToStaticMarkup(createElement(CodeModeInfoBody))

    expect(html).toContain("working through data without back-and-forth")
    expect(html).toContain("run an ads report")
    expect(html).toContain("Leave it off for simple chat or single-action agents")
  })
})

function renderSection(toolCatalog: ToolCatalogEntry[]) {
  return renderToStaticMarkup(
    createElement(AgentToolsSection, {
      onCodeModeEnabledChange: vi.fn(),
      onToolModeChange: vi.fn(),
      state: initialAgentFormState(null, toolCatalog),
      toolCatalog,
    })
  )
}
