import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { resourceTablesQueryOptions } from "@/features/integrations/api/list-resource-tables"
import { tableScopesQueryOptions } from "@/features/integrations/api/list-table-scopes"
import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import { ResourceSelectionPanel } from "@/features/integrations/components/resource-selection-panel"
import type {
  IntegrationConnection,
  IntegrationResource,
  TableScopeRule,
} from "@/features/integrations/types"

const connection: IntegrationConnection = {
  connected_by_user_id: "user-1",
  created_at: "2026-08-25T10:00:00Z",
  credential: null,
  discovery_in_flight: false,
  duplicate_of_connection_ids: [],
  id: "connection-1",
  label: "Warehouse",
  latest_discovery_run: null,
  owner_scope: "workspace",
  owner_user_id: null,
  owner_workspace_id: "workspace-1",
  provider_key: "bigquery",
  status: "active",
  status_reason: null,
  updated_at: "2026-08-25T10:00:00Z",
}

const resources: IntegrationResource[] = [
  {
    availability: "available",
    connection_id: connection.id,
    connection_owner_scope: "workspace",
    enabled: true,
    external_id: "project.marketing",
    first_seen_at: "2026-08-25T10:00:00Z",
    id: "resource-1",
    last_seen_at: "2026-08-25T10:00:00Z",
    metadata: {},
    parent_external_id: null,
    provider_key: "bigquery",
    removed_at: null,
    resource_type: "bigquery_dataset",
    display_name: "Marketing",
    writable: false,
  },
]

const rule: TableScopeRule = {
  allowed_values: ["client-1", "client-2", "client-3", "client-4"],
  column_name: "account_id",
  column_type: "string",
  id: "rule-1",
  resource_display_name: "Marketing",
  resource_external_id: "project.marketing",
  resource_id: "resource-1",
  table_external_id: "campaign_daily",
}

describe("table scope row filters", () => {
  it("keeps table-scope reads on their workspace-scoped query keys", () => {
    expect(tableScopesQueryOptions(connection.id).queryKey).toEqual(
      integrationsQueryKeys.tableScopes(connection.id)
    )
    expect(
      resourceTablesQueryOptions({
        connectionId: connection.id,
        enabled: true,
        resourceId: resources[0]?.id ?? "",
      }).queryKey
    ).toEqual(integrationsQueryKeys.resourceTables(connection.id, "resource-1"))
  })

  it("offers a per-row filter action only for supported, enabled resources", () => {
    expect(renderPanel(true, [])).toContain("Add Filter")
    expect(renderPanel(false, [])).not.toContain("Add Filter")
    expect(
      renderPanel(
        true,
        [],
        resources.map((resource) => ({ ...resource, enabled: false }))
      )
    ).not.toContain("Add Filter")
  })

  it("renders each rule on its data source row with a bounded value summary", () => {
    const html = renderPanel(true, [rule])
    expect(html).toContain("campaign_daily")
    expect(html).toContain("account_id")
    expect(html).toContain("client-1, client-2, client-3")
    expect(html).toContain("+1 more")
  })

  it("shows the tables-only footnote only while a filter exists", () => {
    const html = renderPanel(true, [rule])
    expect(html).toContain("agents can query tables only")
    expect(html).toContain("Remove a data source&#x27;s filters before turning it off")
    expect(html).toMatch(/aria-describedby="table-scope-filter-note-connection-1"[^>]*disabled/)
    expect(renderPanel(true, [])).not.toContain("agents can query tables only")
  })
})

function renderPanel(
  tableScopesSupported: boolean,
  rules: TableScopeRule[],
  resourceList: IntegrationResource[] = resources
) {
  const queryClient = new QueryClient()
  queryClient.setQueryData(integrationsQueryKeys.resources(connection.id), resourceList)
  queryClient.setQueryData(integrationsQueryKeys.tableScopes(connection.id), {
    connection_id: connection.id,
    rules,
  })
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(ResourceSelectionPanel, {
        canEdit: true,
        connection,
        tableScopesSupported,
      })
    )
  )
}
