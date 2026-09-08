// apps/web/src/components/tool-ui/edited-values.ts

export type EditedScalar = string | number | boolean
export type EditedKeyValue = Record<string, EditedScalar>
export type EditedRecordCell = string | number | string[] | EditedKeyValue
type EditedRecord = Record<string, EditedRecordCell>
export type EditedRecords = EditedRecord[]
type EditedReference = Record<string, unknown>
export type EditedValue =
  EditedScalar | string[] | EditedKeyValue | EditedRecords | EditedReference | EditedReference[]
export type EditedValues = Record<string, EditedValue>
