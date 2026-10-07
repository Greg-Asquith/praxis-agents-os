import { describe, expect, it } from "vitest"

import { listAllPages } from "@/lib/api/list-all-pages"

describe("list all pages", () => {
  it("collects later records using the number actually returned as the offset", async () => {
    const records = Array.from({ length: 105 }, (_, id) => id)
    const result = await listAllPages((offset) =>
      Promise.resolve({
        items: records.slice(offset, offset + 40),
        total: records.length,
      })
    )
    expect(result).toEqual(records)
  })

  it("stops when a shrinking list returns an empty page", async () => {
    const result = await listAllPages((offset) =>
      Promise.resolve({
        items: offset === 0 ? [1, 2] : [],
        total: 10,
      })
    )
    expect(result).toEqual([1, 2])
  })
})
