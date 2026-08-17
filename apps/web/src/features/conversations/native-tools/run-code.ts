// apps/web/src/features/conversations/native-tools/run-code.ts

import { isRecord } from "@/lib/guards"

export const RUN_CODE_TOOL_NAME = "run_code"

type RunCodeStoredOutput = {
  kind: "artifact" | "file"
  mediaType: string
  name: string
  reference: {
    entityId: string
    entityKind: "artifact" | "file"
    label: string
  }
  sizeBytes: number
}

export type RunCodeResult = {
  model: string
  modelProvider: string
  outputs: RunCodeStoredOutput[]
  result: string
  skippedOutputs: string[]
}

export function runCodeResult(value: unknown): RunCodeResult | null {
  if (!isRecord(value)) {
    return null
  }
  const result = untrustedText(value["result"])
  const rawOutputs = value["outputs"]
  const rawSkipped = value["skipped_outputs"]
  if (
    result === null ||
    !Array.isArray(rawOutputs) ||
    !Array.isArray(rawSkipped) ||
    !rawSkipped.every((item): item is string => typeof item === "string") ||
    typeof value["model_provider"] !== "string" ||
    typeof value["model"] !== "string"
  ) {
    return null
  }
  const outputs = rawOutputs.map(runCodeStoredOutput)
  if (outputs.some((output) => output === null)) {
    return null
  }
  return {
    model: value["model"],
    modelProvider: value["model_provider"],
    outputs: outputs.filter((output): output is RunCodeStoredOutput => output !== null),
    result,
    skippedOutputs: rawSkipped,
  }
}

function runCodeStoredOutput(value: unknown): RunCodeStoredOutput | null {
  if (!isRecord(value) || !isRecord(value["reference"])) {
    return null
  }
  const reference = value["reference"]
  const kind = value["kind"]
  const entityKind = reference["entity_kind"]
  if (
    (kind !== "artifact" && kind !== "file") ||
    entityKind !== kind ||
    typeof value["name"] !== "string" ||
    typeof value["size_bytes"] !== "number" ||
    typeof value["media_type"] !== "string" ||
    typeof reference["entity_id"] !== "string" ||
    typeof reference["label"] !== "string"
  ) {
    return null
  }
  return {
    kind,
    mediaType: value["media_type"],
    name: value["name"],
    reference: {
      entityId: reference["entity_id"],
      entityKind: kind,
      label: reference["label"],
    },
    sizeBytes: value["size_bytes"],
  }
}

function untrustedText(value: unknown): string | null {
  if (typeof value === "string") {
    return value
  }
  if (
    isRecord(value) &&
    value["node"] === "praxis_untrusted" &&
    typeof value["content"] === "string"
  ) {
    return value["content"]
  }
  return null
}
