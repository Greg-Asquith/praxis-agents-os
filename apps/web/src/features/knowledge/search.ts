// apps/web/src/features/knowledge/search.ts

export type KnowledgeSearch = {
  scope?: "workspace" | "platform"
  page?: number
}

export function validateKnowledgeSearch(search: Record<string, unknown>): KnowledgeSearch {
  const page = Number(search["page"])
  return {
    ...(search["scope"] === "workspace" || search["scope"] === "platform"
      ? { scope: search["scope"] }
      : {}),
    ...(Number.isSafeInteger(page) && page > 1 ? { page } : {}),
  }
}
