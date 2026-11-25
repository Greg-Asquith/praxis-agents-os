// apps/web/src/features/knowledge/search.ts

import { validateListSearch, type ListSearch } from "@/lib/list-search"

export type KnowledgeSearch = Pick<ListSearch<never>, "page" | "q" | "scope">

const NO_SORT_FIELDS = new Set<never>()

export function validateKnowledgeSearch(search: Record<string, unknown>): KnowledgeSearch {
  const { page, q, scope } = validateListSearch(search, NO_SORT_FIELDS)
  return { ...(page ? { page } : {}), ...(q ? { q } : {}), ...(scope ? { scope } : {}) }
}
