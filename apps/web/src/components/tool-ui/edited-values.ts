// apps/web/src/components/tool-ui/edited-values.ts

export type EditedScalar = string | number | boolean
export type EditedKeyValue = Record<string, EditedScalar>
type EditedReference = Record<string, unknown>
export type EditedValue =
  string | number | string[] | EditedKeyValue | EditedReference | EditedReference[]
export type EditedValues = Record<string, EditedValue>
