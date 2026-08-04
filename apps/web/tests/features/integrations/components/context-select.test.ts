import { createElement, type ComponentPropsWithoutRef, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ContextSelect } from "@/features/integrations/components/context-select"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"

type ChildrenProps = {
  children?: ReactNode
  className?: string
}

type MockLinkProps = Omit<ComponentPropsWithoutRef<"a">, "href"> & {
  to: string
}

vi.mock("@tanstack/react-router", async () => {
  const React = await import("react")
  return {
    Link: ({ to, ...props }: MockLinkProps) => React.createElement("a", { ...props, href: to }),
  }
})

vi.mock("@/components/ui/checkbox", () => ({
  Checkbox: ({
    checked,
    className,
    disabled,
    id,
  }: {
    checked?: boolean
    className?: string
    disabled?: boolean
    id?: string
  }) =>
    createElement("input", {
      checked,
      className,
      disabled,
      id,
      readOnly: true,
      type: "checkbox",
    }),
}))

vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: ChildrenProps) => createElement("div", null, children),
  PopoverContent: ({ children, className }: ChildrenProps) =>
    createElement("div", { className }, children),
  PopoverDescription: ({ children }: ChildrenProps) => createElement("p", null, children),
  PopoverHeader: ({ children, className }: ChildrenProps) =>
    createElement("div", { className }, children),
  PopoverTitle: ({ children }: ChildrenProps) => createElement("h2", null, children),
  PopoverTrigger: ({ children, render }: ChildrenProps & { render: ReactNode }) =>
    createElement("div", { "data-has-render": Boolean(render) }, children),
}))

vi.mock("@/features/integrations/components/provider-mark", () => ({
  ProviderMark: ({ providerKey }: { providerKey: string }) =>
    createElement("span", { "data-provider-key": providerKey }),
}))

const group: IntegrationContextGroup = {
  id: "group-1",
  workspace_id: "workspace-1",
  name: "Client X",
  created_by_user_id: "user-1",
  created_at: "2026-08-04T10:00:00Z",
  updated_at: "2026-08-04T10:00:00Z",
  members: [],
}

const personalResource: IntegrationResource = {
  id: "resource-1",
  connection_id: "connection-1",
  resource_type: "gmail_mailbox",
  external_id: "owner@example.com",
  display_name: "owner@example.com",
  parent_external_id: null,
  enabled: true,
  availability: "available",
  writable: true,
  metadata: {},
  first_seen_at: "2026-08-04T10:00:00Z",
  last_seen_at: "2026-08-04T10:00:00Z",
  removed_at: null,
  connection_owner_scope: "user",
  provider_key: "gmail",
  connection_label: "Personal Gmail",
  connection_status: "active",
}

function renderContextSelect({
  showPersonalBadges = true,
  value = [{ type: "resource", integration_resource_id: personalResource.id }],
}: {
  showPersonalBadges?: boolean
  value?: ActiveContextSelectionValue[]
} = {}) {
  return renderToStaticMarkup(
    createElement(ContextSelect, {
      contextGroups: [group],
      onChange: vi.fn(),
      resources: [personalResource],
      showManageIntegrations: true,
      showPersonalBadges,
      value,
    })
  )
}

describe("ContextSelect", () => {
  it("renders shared-workspace personal context and semantic navigation", () => {
    const markup = renderContextSelect()

    expect(markup).toContain("Personal — only you can use this")
    expect(markup).toContain('href="/integrations"')
    expect(markup).toContain("w-[min(24rem,calc(100vw-1rem))]")
    expect(markup).toContain("overscroll-contain")
  })

  it("hides personal badges in personal workspaces", () => {
    expect(renderContextSelect({ showPersonalBadges: false })).not.toContain(
      "Personal — only you can use this"
    )
  })

  it("renders unavailable selections and disables new options at the target cap", () => {
    const value = Array.from({ length: 10 }, (_, index) => ({
      integration_resource_id: `missing-${String(index)}`,
      type: "resource" as const,
    }))
    const markup = renderContextSelect({ value })
    const availableResourceOption =
      /<label[^>]*for="[^"]*resource:resource-1"[\s\S]*?<\/label>/.exec(markup)?.[0]

    expect(markup.match(/Selected context is unavailable/g)).toHaveLength(10)
    expect(availableResourceOption).toContain("disabled")
  })
})
