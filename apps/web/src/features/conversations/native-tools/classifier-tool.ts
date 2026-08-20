// apps/web/src/features/conversations/native-tools/classifier-tool.ts

import { normalizeToolArgs } from "@/features/conversations/message-parts"

import { isNonNegativeInteger, isRecord } from "@/lib/guards"

export const CLASSIFY_TOOL_NAME = "classify"
const CLASSIFIER_TOOL_PREFIX = "classifier_"

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

export function isClassifierToolName(name: string) {
  return name === CLASSIFY_TOOL_NAME || name.startsWith(CLASSIFIER_TOOL_PREFIX)
}

export function classifierItems(value: unknown): string[] | null {
  const args = normalizeToolArgs(value)
  if (
    !isRecord(args) ||
    !isStringArray(args["items"]) ||
    args["items"].length === 0 ||
    args["items"].some((item) => !item.trim())
  ) {
    return null
  }
  return args["items"]
}

export function classifierArgs(value: unknown): ClassifierArgs | null {
  const args = normalizeToolArgs(value)
  const items = classifierItems(value)
  if (
    !isRecord(args) ||
    items === null ||
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
    items,
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
  const classifiedRows = rows.filter(isClassifiedItem)
  if (classifiedRows.length !== rows.length) {
    return null
  }

  return {
    labels: args?.labels ?? [...new Set(classifiedRows.map((row) => row.label))],
    model: resultValue["model"],
    modelProvider: resultValue["model_provider"],
    rows: classifiedRows,
  }
}

function isClassifiedItem(value: ClassifiedItem | null): value is ClassifiedItem {
  return value !== null
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}
