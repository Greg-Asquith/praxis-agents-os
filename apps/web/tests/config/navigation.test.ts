// apps/web/tests/config/navigation.test.ts

import { createElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { PrimaryNavigation } from "@/components/shell/primary-navigation"
import { navigationItemsForRole } from "@/config/navigation"

vi.mock("@tanstack/react-router", async () => {
  const { createElement } = await import("react")

  return {
    Link: ({ children, className, to }: { children: ReactNode; className?: string; to: string }) =>
      createElement("a", { className, href: to }, children),
  }
})

describe("navigationItemsForRole", () => {
  it.each([null, "member", "admin", "owner"])(
    "keeps the primary navigation focused for the %s role",
    (role) => {
      expect(
        navigationItemsForRole(role).map(({ label, to }) => ({
          label,
          to,
        }))
      ).toEqual([
        { label: "Home", to: "/" },
        { label: "Agents", to: "/agents" },
        { label: "Context", to: "/context" },
        { label: "Schedules", to: "/schedules" },
        { label: "Integrations", to: "/integrations" },
      ])
    }
  )

  it("groups all six context sections under the Context item", () => {
    const contextItem = navigationItemsForRole("member").find((item) => item.label === "Context")

    expect(contextItem).toMatchObject({
      activeWhen: [
        "/skills",
        "/memories",
        "/knowledge",
        "/files",
        "/artifacts",
        "/integrations/context-groups",
      ],
    })
  })
})

describe("PrimaryNavigation active item", () => {
  it.each([
    ["/context", "Context"],
    ["/skills/abc", "Context"],
    ["/memories", "Context"],
    ["/artifacts/abc", "Context"],
    ["/integrations/context-groups", "Context"],
    ["/integrations/gmail", "Integrations"],
    ["/agents", "Agents"],
  ])("selects %s as %s", (pathname, expectedLabel) => {
    const html = renderNavigation(pathname)

    expect(activeLinkLabel(html)).toBe(expectedLabel)
  })

  it("does not select Context outside its paths", () => {
    expect(activeLinkLabel(renderNavigation("/"))).toBe("Home")
    expect(activeLinkLabel(renderNavigation("/agents"))).not.toBe("Context")
  })
})

function renderNavigation(pathname: string) {
  return renderToStaticMarkup(
    createElement(PrimaryNavigation, {
      pathname,
      workspaceRole: "member",
    })
  )
}

function activeLinkLabel(html: string) {
  for (const match of html.matchAll(/<a class="([^"]*)" href="[^"]*">(.*?)<\/a>/g)) {
    if (match[1]?.split(" ").includes("bg-sidebar-accent")) {
      const linkContent = match[2]
      return linkContent?.slice(linkContent.lastIndexOf(">") + 1) ?? null
    }
  }

  return null
}
