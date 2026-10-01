// apps/web/tests/features/conversations/document-tools.test.ts

import { describe, expect, it } from "vitest"

import {
  documentOperationSummaries,
  documentToolResult,
} from "@/features/conversations/native-tools/document-tools"

describe("document tool results", () => {
  it("leaves an unrecognised edit result to the generic row", () => {
    // A write_file-shaped result has no revision_number or changes.
    const result = documentToolResult("edit_workbook", {
      file_id: "file-1",
      name: "Regional sales.xlsx",
      revision_id: "revision-2",
      bytes_written: 4096,
    })

    expect(result).toBeNull()
  })
})

describe("document operation summaries", () => {
  it("aggregates operations per kind and target and buckets unknown ones together", () => {
    const summaries = documentOperationSummaries({
      operations: [
        { op: "set_cells", sheet: "Sales", values: [[1, 2], [3]] },
        { op: "set_cells", sheet: "Sales", values: [[4]] },
        { op: "set_cells", sheet: "Costs", values: [[5]] },
        { op: "future_op" },
        { op: "another_future_op" },
      ],
    })

    expect(summaries).toHaveLength(3)
    expect(summaries[0]).toMatch(/\b4\b.*Sales$/)
    expect(summaries[1]).toMatch(/\b1\b.*Costs$/)
    expect(summaries[2]).toMatch(/\b2\b/)
  })
})
