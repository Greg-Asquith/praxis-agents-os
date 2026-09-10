// apps/web/tests/integrations/microsoft-module-contract.ts

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"

import type { IntegrationProvider } from "@/features/integrations/types"
import type { IntegrationUiModule } from "@/integrations/contract"
import {
  integrationIcon,
  integrationToolRowPresenters,
  loadIntegrationUiModules,
  providerKeyForToolName,
} from "@/integrations/registry"

type MicrosoftModuleContract = {
  description: string
  displayName: string
  module: IntegrationUiModule
  providerKey: string
  resourceType: string
}

export function testMicrosoftIntegrationModule(contract: MicrosoftModuleContract) {
  it("loads lazily through the registry with its declared tool presenters", async () => {
    await loadIntegrationUiModules([contract.providerKey])

    expect(providerKeyForToolName(`${contract.providerKey}_future_tool`)).toBe(contract.providerKey)
    expect(integrationIcon(contract.providerKey)).toBe(contract.module.Logo)
    expect(integrationToolRowPresenters(contract.providerKey)).toEqual(
      contract.module.toolRowPresenters ?? []
    )
    expect(contract.module.catalogDescription).toBe(contract.description)
  })

  it("explains administrator approval, separate grants, and removal", () => {
    const ConnectHelp = contract.module.ConnectHelp
    expect(ConnectHelp).toBeDefined()
    if (!ConnectHelp) {
      throw new Error("Microsoft integration module is missing ConnectHelp")
    }
    const provider: IntegrationProvider = {
      auth_modes: ["oauth"],
      capability_flags: ["read"],
      configured: true,
      configured_auth_modes: { oauth: true },
      display_name: contract.displayName,
      knowledge_source_resource_types: [],
      knowledge_source_supported: false,
      oauth_scopes: [],
      owner_scope: "user",
      provider_key: contract.providerKey,
      required_form_fields: [],
      requires_discovery: true,
      resource_types: [contract.resourceType],
      table_scopes_supported: false,
    }
    const html = renderToStaticMarkup(createElement(ConnectHelp, { provider }))

    expect(html).toContain("administrator sets up and approves")
    expect(html).toContain("approval or assignment")
    expect(html).toContain("doesn&#x27;t connect Outlook Mail, Outlook Calendar, or SharePoint")
    expect(html).toContain("https://myapps.microsoft.com")
  })
}
