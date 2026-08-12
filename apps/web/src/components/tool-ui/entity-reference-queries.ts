import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query"

import type {
  EntityChoice,
  EntityReferenceLookupResponse,
  EntityReferenceValue,
} from "@/features/tools/types"
import { apiRequest } from "@/lib/api/client"
import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseEntityReferenceQueryKeys = createWorkspaceScopedQueryKeys("tool-entity-references")

type LookupBase = {
  conversationId: string
  toolName: string
  fieldKey: string
  dependentArgs: Record<string, unknown>
}

export type EntityReferenceSearch = LookupBase & {
  search: string
  pageSize?: number
}

export type EntityReferenceHydration = LookupBase & {
  exactValues: EntityReferenceValue[]
}

const entityReferenceQueryKeys = {
  ...baseEntityReferenceQueryKeys,
  field: ({ conversationId, dependentArgs, fieldKey, toolName }: LookupBase) =>
    [
      ...baseEntityReferenceQueryKeys.workspace(),
      conversationId,
      toolName,
      fieldKey,
      dependentArgs,
    ] as const,
  hydration: (request: EntityReferenceHydration) =>
    [...entityReferenceQueryKeys.field(request), "hydrate", request.exactValues] as const,
  search: (request: EntityReferenceSearch) =>
    [...entityReferenceQueryKeys.field(request), "search", request.search] as const,
}

async function lookupEntityReferences(
  request: LookupBase & {
    search?: string
    exactValues?: EntityReferenceValue[]
    cursor?: string | null
    pageSize?: number
  },
  signal?: AbortSignal
) {
  return apiRequest<EntityReferenceLookupResponse>(
    `/tools/conversations/${encodeURIComponent(request.conversationId)}/entity-references`,
    {
      method: "POST",
      ...(signal ? { signal } : {}),
      body: {
        tool_name: request.toolName,
        field_key: request.fieldKey,
        dependent_args: request.dependentArgs,
        ...(request.search !== undefined ? { search: request.search } : {}),
        ...(request.exactValues !== undefined ? { exact_values: request.exactValues } : {}),
        ...(request.cursor ? { cursor: request.cursor } : {}),
        ...(request.pageSize ? { page_size: request.pageSize } : {}),
      },
    }
  )
}

export function entityReferenceHydrationQueryOptions(request: EntityReferenceHydration) {
  return queryOptions({
    queryKey: entityReferenceQueryKeys.hydration(request),
    queryFn: ({ signal }) => lookupEntityReferences(request, signal),
    staleTime: 30_000,
  })
}

export function entityReferenceSearchQueryOptions(request: EntityReferenceSearch) {
  return infiniteQueryOptions({
    queryKey: entityReferenceQueryKeys.search(request),
    queryFn: ({ pageParam, signal }) =>
      lookupEntityReferences({ ...request, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
    staleTime: 15_000,
  })
}

export function mergeEntityChoices(
  hydrated: EntityChoice[],
  pages: { choices: EntityChoice[] }[]
): EntityChoice[] {
  const choices = new Map<string, EntityChoice>()
  for (const choice of [...hydrated, ...pages.flatMap((page) => page.choices)]) {
    choices.set(entityReferenceKey(choice.value), choice)
  }
  return [...choices.values()]
}

// Identity excludes defaulted fields (entity_kind, version): model-issued args
// may omit them while server-canonical choices always carry them.
export function entityReferenceKey(value: EntityReferenceValue): string {
  return JSON.stringify([
    value["entity_id"],
    value["integration_resource_id"],
    value["external_id"],
    value["table"],
  ])
}
