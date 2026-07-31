// apps/web/src/components/tool-ui/edited-values.ts

export type EditedScalar = string | number | boolean
export type EditedKeyValue = Record<string, EditedScalar>
export type EditedValue = string | number | string[] | EditedKeyValue
export type EditedValues = Record<string, EditedValue>
