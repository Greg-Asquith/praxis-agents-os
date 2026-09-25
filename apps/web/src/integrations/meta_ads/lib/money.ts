// apps/web/src/integrations/meta_ads/lib/money.ts

export function isMoneyField(field: string): boolean {
  return (
    field === "spend" ||
    field === "social_spend" ||
    field === "cpc" ||
    field === "cpm" ||
    field === "cpp" ||
    field === "action_values" ||
    field === "conversion_values" ||
    field.startsWith("cost_per_")
  )
}
