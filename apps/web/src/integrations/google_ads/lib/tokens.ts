// apps/web/src/integrations/google_ads/lib/tokens.ts

const ADVERTISING_ACRONYMS = new Set(["CPA", "CPC", "CPM", "CPV", "ROAS", "ID", "URL"])

export function googleAdsTokenLabel(value: string, fallback = ""): string {
  return (
    value
      .split("_")
      .filter(Boolean)
      .map((word) => {
        const upper = word.toUpperCase()
        return ADVERTISING_ACRONYMS.has(upper)
          ? upper
          : `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`
      })
      .join(" ") || fallback
  )
}
