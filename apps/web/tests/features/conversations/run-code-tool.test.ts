import { describe, expect, it } from "vitest"

import { runCodeResult } from "@/features/conversations/native-tools/run-code"

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
          sizeBytes: 4096,
        },
      ],
      result: "The total is 42.",
      skippedOutputs: [],
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
})
