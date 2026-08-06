import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { AgentToolProviderGroup } from "@/features/agents/components/agent-tool-provider-group"
import type { ToolGroup } from "@/features/agents/components/agent-tool-catalog-utils"

const group: ToolGroup = {
  provider: "bigquery",
  tools: [
    {
      name: "bigquery_run_query",
      provider: "bigquery",
      label: "Run BigQuery Query",
      description: "Run a bounded query.",
      kind: "function",
      effect: "read",
      effect_scope: "external",
      egress: "external_write",
      default_policy: "approval",
      supported_policies: ["approval"],
      defer_loading: false,
    },
  ],
}

describe("AgentToolProviderGroup", () => {
  it("starts collapsed even when the provider has active tools", () => {
    const html = renderGroup({ forceOpen: false, toolModes: { bigquery_run_query: "approval" } })

    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain("1 active")
    expect(html).not.toContain("Run a bounded query.")
  })

  it("opens matching providers while searching", () => {
    const html = renderGroup({ forceOpen: true, toolModes: {} })

    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("Run a bounded query.")
  })
})

function renderGroup({
  forceOpen,
  toolModes,
}: {
  forceOpen: boolean
  toolModes: Record<string, "off" | "approval" | "auto">
}) {
  return renderToStaticMarkup(
    createElement(AgentToolProviderGroup, {
      forceOpen,
      group,
      onModeChange: () => undefined,
      onOpenChange: () => undefined,
      openOverride: undefined,
      toolModes,
    })
  )
}
