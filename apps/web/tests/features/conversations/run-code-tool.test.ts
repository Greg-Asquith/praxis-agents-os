import { describe, expect, it } from "vitest"

import {
  runCodeResult,
  runCodeTouchedFileIds,
} from "@/features/conversations/native-tools/run-code"

describe("runCodeResult", () => {
  it("parses framed results and retained file references", () => {
    expect(
      runCodeResult({
        model: "gpt-5.6-luna",
        model_provider: "openai",
        outputs: [
          {
            kind: "file",
            media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            name: "summary.xlsx",
            reference: {
              entity_id: "file-1",
              entity_kind: "file",
              label: "summary.xlsx",
            },
            size_bytes: 4096,
          },
        ],
        result: {
          node: "praxis_untrusted",
          source_kind: "run_code_output",
          source_ref: "run-1",
          content: "The total is 42.",
        },
        skipped_outputs: [],
      })
    ).toEqual({
      model: "gpt-5.6-luna",
      modelProvider: "openai",
      outputs: [
        {
          kind: "file",
          mediaType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          name: "summary.xlsx",
          reference: { entityId: "file-1", entityKind: "file", label: "summary.xlsx" },
          revisionId: null,
          revisionNumber: null,
          sizeBytes: 4096,
          updatedExisting: false,
        },
      ],
      result: "The total is 42.",
      skippedOutputs: [],
    })
  })

  it("parses a source-file revision retained from a declared edit", () => {
    const result = runCodeResult({
      model: "claude-sonnet-5",
      model_provider: "anthropic",
      outputs: [
        {
          kind: "file",
          media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          name: "budget.xlsx",
          reference: {
            entity_id: "file-1",
            entity_kind: "file",
            label: "budget.xlsx",
          },
          revision_id: "revision-2",
          revision_number: 2,
          size_bytes: 8192,
          updated_existing: true,
        },
      ],
      result: "Updated the workbook.",
      skipped_outputs: [],
    })

    expect(result?.outputs[0]).toMatchObject({
      name: "budget.xlsx",
      revisionId: "revision-2",
      revisionNumber: 2,
      updatedExisting: true,
    })
  })

  it("rejects malformed output references", () => {
    expect(
      runCodeResult({
        model: "gpt-5.6-luna",
        model_provider: "openai",
        outputs: [{ kind: "file", reference: { entity_kind: "artifact" } }],
        result: "Done",
        skipped_outputs: [],
      })
    ).toBeNull()
  })

  it("lists workspace files created or updated by a result for cache invalidation", () => {
    const output = (kind: "artifact" | "file", id: string, updated = false) => ({
      kind,
      media_type: "text/plain",
      name: `${id}.txt`,
      reference: { entity_id: id, entity_kind: kind, label: `${id}.txt` },
      size_bytes: 1,
      updated_existing: updated,
    })

    expect(
      runCodeTouchedFileIds({
        model: "gpt-5.6-luna",
        model_provider: "openai",
        outputs: [
          output("file", "file-1", true),
          output("artifact", "art-1"),
          output("file", "file-2"),
        ],
        result: "Done",
        skipped_outputs: [],
      })
    ).toEqual(["file-1", "file-2"])
    expect(runCodeTouchedFileIds({ not: "a result" })).toEqual([])
  })
})
