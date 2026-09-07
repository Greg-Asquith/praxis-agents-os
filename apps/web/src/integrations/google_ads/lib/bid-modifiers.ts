// apps/web/src/integrations/google_ads/lib/bid-modifiers.ts

const MULTIPLIER_FORMAT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const PERCENT_FORMAT = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
  signDisplay: "never",
  style: "percent",
})

export function formatBidAdjustment(value: number): string {
  const multiplier = `${MULTIPLIER_FORMAT.format(value)}×`
  if (value === 0) {
    return `Exclude (${multiplier})`
  }
  if (value === 1) {
    return `No adjustment (${multiplier})`
  }
  const percentage = PERCENT_FORMAT.format(Math.abs(value - 1))
  return `${value > 1 ? "Raise" : "Lower"} by ${percentage} (${multiplier})`
}
