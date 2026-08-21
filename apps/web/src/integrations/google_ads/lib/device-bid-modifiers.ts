// apps/web/src/integrations/google_ads/lib/device-bid-modifiers.ts

const MULTIPLIER_FORMAT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const PERCENT_FORMAT = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
  signDisplay: "never",
  style: "percent",
})
const ADVERTISING_ACRONYMS = new Set(["CPA", "CPC", "CPM", "CPV", "ROAS"])

export function formatDeviceBidAdjustment(value: number): string {
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

export function humanizeGoogleAdsToken(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((word) =>
      ADVERTISING_ACRONYMS.has(word)
        ? word
        : `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`
    )
    .join(" ")
}
