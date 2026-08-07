// apps/web/src/components/tool-ui/edited-values.ts

export type EditedScalar = string | number | boolean
export type EditedKeyValue = Record<string, EditedScalar>
export type EditedRecord = Record<string, string | number>
export type EditedRecords = EditedRecord[]
type EditedReference = Record<string, unknown>
export type EditedValue =
  string | number | string[] | EditedKeyValue | EditedRecords | EditedReference | EditedReference[]
export type EditedValues = Record<string, EditedValue>
