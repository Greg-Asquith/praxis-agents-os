// apps/web/src/lib/list-search.ts

import { isOneOf } from "@/lib/guards"

const MAX_QUERY_LENGTH = 255

// URL state shared by the paginated list routes; features add their own fields.
export type ListSearch<SortField extends string> = {
  direction?: "asc" | "desc"
  page?: number
  q?: string
  scope?: "workspace" | "platform"
  sort?: SortField
}

export type SearchPatch<Search> = { [Key in keyof Search]?: Search[Key] | undefined }

export function validateListSearch<SortField extends string>(
  search: Record<string, unknown>,
  sortFields: ReadonlySet<SortField>
): ListSearch<SortField> {
  const result: ListSearch<SortField> = {}
  const query = typeof search["q"] === "string" ? search["q"].trim().slice(0, MAX_QUERY_LENGTH) : ""
  if (query) {
    result.q = query
  }
  const scope = search["scope"]
  if (scope === "workspace" || scope === "platform") {
    result.scope = scope
  }
  const page = Number(search["page"])
  if (Number.isSafeInteger(page) && page > 1) {
    result.page = page
  }
  const sort = search["sort"]
  if (isOneOf(sortFields, sort)) {
    result.sort = sort
  }
  const direction = search["direction"]
  if (direction === "asc" || direction === "desc") {
    result.direction = direction
  }
  return result
}

// URL state for list pages that only search and page.
export type PagedSearch = Pick<ListSearch<never>, "page" | "q">

const NO_SORT_FIELDS = new Set<never>()

export function validatePagedSearch(search: Record<string, unknown>): PagedSearch {
  const { page, q } = validateListSearch(search, NO_SORT_FIELDS)
  return { ...(page ? { page } : {}), ...(q ? { q } : {}) }
}

// Drops defaults so the URL only carries state that differs from a fresh visit.
export function normalisePagedSearch(next: SearchPatch<PagedSearch>): PagedSearch {
  return {
    ...(next.page && next.page > 1 ? { page: next.page } : {}),
    ...(next.q ? { q: next.q } : {}),
  }
}
