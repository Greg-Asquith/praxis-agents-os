import { describe, expect, it } from "vitest"

import {
  availableKnowledgeSourceResources,
  buildIntegrationImportPayload,
  eligibleKnowledgeSourceProviders,
  INTEGRATION_IMPORT_IS_PRIVATE_DEFAULT,
  integrationImportErrorMessage,
  integrationImportResourceState,
  validateIntegrationImportForm,
} from "@/features/knowledge/components/integration-import-form-model"
import type {
  IntegrationConnection,
  IntegrationProvider,
  IntegrationResource,
} from "@/features/integrations/types"

const provider: IntegrationProvider = {
  auth_modes: ["oauth"],
  capability_flags: [],
  configured: true,
  configured_auth_modes: { oauth: true },
  display_name: "Notion",
  knowledge_source_supported: true,
  knowledge_source_resource_types: ["notion_workspace"],
  oauth_scopes: [],
  owner_scope: "user",
  provider_key: "notion",
  required_form_fields: [],
  requires_discovery: true,
  resource_types: ["notion_workspace"],
  table_scopes_supported: false,
}

function connection(overrides: Partial<IntegrationConnection> = {}): IntegrationConnection {
  return {
    connected_by_user_id: "user-1",
    created_at: "2026-08-28T10:00:00Z",
    credential: null,
    discovery_in_flight: false,
    duplicate_of_connection_ids: [],
    id: "connection-1",
    label: "Example Organization",
    latest_discovery_run: null,
    owner_scope: "user",
    owner_user_id: "user-1",
    owner_workspace_id: null,
    provider_key: "notion",
    status: "active",
    status_reason: null,
    updated_at: "2026-08-28T10:00:00Z",
    ...overrides,
  }
}

function resource(overrides: Partial<IntegrationResource> = {}): IntegrationResource {
  return {
    availability: "available",
    connection_id: "connection-1",
    connection_owner_scope: "user",
    display_name: "Example Organization",
    enabled: true,
    external_id: "workspace-1",
    first_seen_at: "2026-08-28T10:00:00Z",
    id: "resource-1",
    last_seen_at: "2026-08-28T10:00:00Z",
    metadata: {},
    parent_external_id: null,
    removed_at: null,
    resource_type: "notion_workspace",
    writable: false,
    ...overrides,
  }
}

describe("integration Knowledge Base import form", () => {
  it("starts private and preserves explicit workspace sharing", () => {
    expect(INTEGRATION_IMPORT_IS_PRIVATE_DEFAULT).toBe(true)
    expect(
      buildIntegrationImportPayload({
        integrationResourceId: "resource-1",
        isPrivate: false,
        source: { page_id: "page-1" },
        title: "  Team handbook  ",
      })
    ).toEqual({
      integration_resource_id: "resource-1",
      is_private: false,
      source: { page_id: "page-1" },
      title: "Team handbook",
    })
  })

  it("validates pasted URLs", () => {
    expect(
      validateIntegrationImportForm({
        integrationResourceId: "resource-1",
        isPrivate: true,
        source: "not a URL",
        title: "",
      })
    ).toEqual([
      {
        fieldId: "knowledge-integration-url",
        label: "Page URL",
        message: "Enter a valid HTTPS URL.",
      },
    ])
    expect(
      validateIntegrationImportForm({
        integrationResourceId: "resource-1",
        isPrivate: true,
        source: "http://www.notion.so/example",
        title: "",
      })
    ).toEqual([
      {
        fieldId: "knowledge-integration-url",
        label: "Page URL",
        message: "Enter a valid HTTPS URL.",
      },
    ])
  })

  it("gates providers to supported usable personal connections", () => {
    expect(
      eligibleKnowledgeSourceProviders(
        [provider, { ...provider, knowledge_source_supported: false, provider_key: "other" }],
        [
          connection(),
          connection({ id: "connection-2", owner_user_id: "user-2" }),
          connection({ id: "connection-3", status: "needs_reauth" }),
        ],
        "user-1"
      ).map((option) => [option.provider.provider_key, option.connections.length])
    ).toEqual([["notion", 1]])
  })

  it("filters unavailable resources and distinguishes load states", () => {
    expect(
      availableKnowledgeSourceResources(
        [
          resource(),
          resource({ id: "resource-2", availability: "unavailable" }),
          resource({ id: "resource-3", removed_at: "2026-08-28T11:00:00Z" }),
          resource({ id: "resource-4", resource_type: "notion_database" }),
        ],
        provider.knowledge_source_resource_types
      ).map((item) => item.id)
    ).toEqual(["resource-1"])
    expect([
      integrationImportResourceState({ hasError: false, isLoading: true, resourceCount: 0 }),
      integrationImportResourceState({ hasError: true, isLoading: false, resourceCount: 0 }),
      integrationImportResourceState({ hasError: false, isLoading: false, resourceCount: 0 }),
      integrationImportResourceState({ hasError: false, isLoading: false, resourceCount: 1 }),
    ]).toEqual(["loading", "error", "empty", "ready"])
  })

  it("keeps provider internals out of error copy", () => {
    expect(
      integrationImportErrorMessage(
        "Notion returned an invalid page response | provider=notion | operation=search"
      )
    ).toBe("Notion returned an invalid page response")
  })
})
