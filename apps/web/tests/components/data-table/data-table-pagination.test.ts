import { describe, expect, it } from "vitest"

import {
  paginationStateFromServer,
  paginationStateToServer,
  sortingStateFromServer,
  sortingStateToServer,
} from "@/components/data-table/server-state"

describe("data table pagination", () => {
  it("translates page indexes to offsets", () => {
    expect(paginationStateToServer({ pageIndex: 0, pageSize: 25 })).toEqual({
      limit: 25,
      offset: 0,
    })
    expect(paginationStateToServer({ pageIndex: 3, pageSize: 25 })).toEqual({
      limit: 25,
      offset: 75,
    })
    expect(paginationStateToServer({ pageIndex: -1, pageSize: 25 })).toEqual({
      limit: 25,
      offset: 0,
    })
  })

  it("translates and clamps offsets to valid page indexes", () => {
    expect(paginationStateFromServer({ limit: 25, offset: 50 }, 80)).toEqual({
      pageIndex: 2,
      pageSize: 25,
    })
    expect(paginationStateFromServer({ limit: 25, offset: -25 }, 80).pageIndex).toBe(0)
    expect(paginationStateFromServer({ limit: 25, offset: 125 }, 80).pageIndex).toBe(3)
    expect(paginationStateFromServer({ limit: 25, offset: 25 }, 0).pageIndex).toBe(0)
  })

  it("translates sorting in both directions and rejects unknown columns", () => {
    const fields = new Set(["name", "updated_at"] as const)
    const fallback = { sort_by: "updated_at", sort_direction: "desc" } as const

    expect(sortingStateFromServer({ sort_by: "name", sort_direction: "asc" })).toEqual([
      { id: "name", desc: false },
    ])
    expect(sortingStateToServer([{ id: "name", desc: true }], fields, fallback)).toEqual({
      sort_by: "name",
      sort_direction: "desc",
    })
    expect(sortingStateToServer([{ id: "unknown", desc: false }], fields, fallback)).toEqual(
      fallback
    )
  })
})
