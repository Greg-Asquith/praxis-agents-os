// apps/web/src/features/conversations/native-tools/classifier-tool.ts

import { normalizeToolArgs } from "@/features/conversations/message-parts"

import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export const CLASSIFY_TOOL_NAME = "classify"

export type ClassifierArgs = {
  instructions: string | null
  items: string[]
  labels: string[]
}

type ClassifiedItem = {
  index: number
  label: string
  value: string
}

export type ClassifierResult = {
  labels: string[]
  model: string
  modelProvider: string
  rows: ClassifiedItem[]
}

export function classifierArgs(value: unknown): ClassifierArgs | null {
  const args = normalizeToolArgs(value)
  if (
    !isRecord(args) ||
    !isStringArray(args["items"]) ||
    args["items"].length === 0 ||
    args["items"].some((item) => !item.trim()) ||
    !isStringArray(args["labels"]) ||
    args["labels"].length < 2 ||
    args["labels"].some((label) => !label.trim())
  ) {
    return null
  }
  const instructions = args["instructions"]
  if (instructions !== undefined && instructions !== null && typeof instructions !== "string") {
    return null
  }
  return {
    instructions: typeof instructions === "string" && instructions.trim() ? instructions : null,
    items: args["items"],
    labels: args["labels"],
  }
}

export function classifierResult(
  argsValue: unknown,
  resultValue: unknown
): ClassifierResult | null {
  const args = classifierArgs(argsValue)
  if (
    !isRecord(resultValue) ||
    !Array.isArray(resultValue["results"]) ||
    resultValue["results"].length === 0 ||
    typeof resultValue["model_provider"] !== "string" ||
    typeof resultValue["model"] !== "string" ||
    (args !== null && resultValue["results"].length !== args.items.length)
  ) {
    return null
  }

  const rows = resultValue["results"].map((value, expectedIndex) => {
    const resultValueText = isRecord(value) ? value["value"] : undefined
    const inputValue = args?.items[expectedIndex]
    if (
      !isRecord(value) ||
      !isNonNegativeInteger(value["index"]) ||
      value["index"] !== expectedIndex ||
      typeof value["label"] !== "string" ||
      !value["label"].trim() ||
      (args !== null && !args.labels.includes(value["label"])) ||
      (resultValueText !== undefined && typeof resultValueText !== "string") ||
      (typeof resultValueText === "string" && !resultValueText.trim()) ||
      (typeof resultValueText === "string" &&
        inputValue !== undefined &&
        resultValueText !== inputValue)
    ) {
      return null
    }
    const classifiedValue = typeof resultValueText === "string" ? resultValueText : inputValue
    if (classifiedValue === undefined) {
      return null
    }
    return {
      index: expectedIndex,
      label: value["label"],
      value: classifiedValue,
    }
  })
  if (rows.some((row) => row === null)) {
    return null
  }

  return {
    labels: args?.labels ?? [...new Set((rows as ClassifiedItem[]).map((row) => row.label))],
    model: resultValue["model"],
    modelProvider: resultValue["model_provider"],
    rows: rows as ClassifiedItem[],
  }
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}
