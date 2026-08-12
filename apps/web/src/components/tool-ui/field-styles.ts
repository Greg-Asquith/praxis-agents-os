// apps/web/src/components/tool-ui/field-styles.ts

export const fieldLabelClass = "text-foreground/75 text-xs leading-4 font-medium tracking-wide"

const fieldWellShape = "min-h-8 w-full min-w-0 rounded-lg px-2.5 py-1 text-sm leading-relaxed"

// Editable inputs keep a real border; read-only wells use a fill instead.
export const fieldWellClass = `${fieldWellShape} border-input border`
export const readOnlyFieldWellClass = `${fieldWellShape} bg-muted/50`
