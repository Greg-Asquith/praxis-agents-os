// apps/web/src/lib/api/list-all-pages.ts

export async function listAllPages<T>(
  fetchPage: (offset: number) => Promise<{ items: T[]; total: number }>
): Promise<T[]> {
  const items: T[] = []
  for (;;) {
    const page = await fetchPage(items.length)
    items.push(...page.items)
    // An empty page means the list shrank while reading, so stop rather than loop.
    if (page.items.length === 0 || items.length >= page.total) return items
  }
}
