// apps/web/tests/features/conversations/components/skill-tool-row.test.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import {
  RouterContextProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router"
import { describe, expect, it } from "vitest"

import { SkillToolRow } from "@/features/conversations/components/skill-tool-row"
import type { ToolActivity } from "@/features/conversations/message-parts"

describe("SkillToolRow", () => {
  it("links found skills to their pages, tolerates results without ids, and names shared owners", () => {
    const html = render({
      id: "tool-1",
      kind: "result",
      name: "search_skills",
      status: "completed",
      args: { query: "report" },
      result: {
        total: 2,
        skills: [
          {
            id: "skill-1",
            name: "weekly-report",
            human_name: "Weekly Report",
            description: "Use for the weekly report.",
            scope: "workspace",
            owner: "Sam",
          },
          {
            name: "shared-report",
            human_name: null,
            description: "Use for the shared report.",
            scope: "platform",
            owner: "Alex",
          },
        ],
      },
    })

    expect(html).toContain('href="/skills/skill-1"')
    expect(html).not.toContain('href="/skills/undefined"')
  })
})

function render(toolActivity: ToolActivity): string {
  const rootRoute = createRootRoute()
  const skillRoute = createRoute({ getParentRoute: () => rootRoute, path: "/skills/$skillId" })
  const router = createRouter({
    history: createMemoryHistory({ initialEntries: ["/"] }),
    routeTree: rootRoute.addChildren([skillRoute]),
  })
  return renderToStaticMarkup(
    createElement(RouterContextProvider, {
      children: createElement(SkillToolRow, { activity: toolActivity, defaultOpen: true }),
      router,
    })
  )
}
