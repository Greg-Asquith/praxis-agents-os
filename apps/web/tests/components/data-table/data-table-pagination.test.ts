import { describe, expect, it } from "vitest"

import { offsetToPageIndex, pageIndexToOffset } from "@/components/data-table/pagination-model"

describe("data table pagination", () => {
  it("translates page indexes to offsets", () => {
    expect(pageIndexToOffset(0, 25)).toBe(0)
    expect(pageIndexToOffset(3, 25)).toBe(75)
    expect(pageIndexToOffset(-1, 25)).toBe(0)
  })

  it("translates and clamps offsets to valid page indexes", () => {
    expect(offsetToPageIndex(50, 25, 80)).toBe(2)
    expect(offsetToPageIndex(-25, 25, 80)).toBe(0)
    expect(offsetToPageIndex(125, 25, 80)).toBe(3)
    expect(offsetToPageIndex(25, 25, 0)).toBe(0)
  })
})
