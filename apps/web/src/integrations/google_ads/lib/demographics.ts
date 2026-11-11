// apps/web/src/integrations/google_ads/lib/demographics.ts

import type { DemographicDimension } from "@/integrations/google_ads/lib/update-targeting"

export const DIMENSION_NAMES: Record<DemographicDimension, string> = {
  AGE_RANGE: "Age",
  GENDER: "Gender",
  PARENTAL_STATUS: "Parental Status",
  INCOME_RANGE: "Household Income",
}

// Google's values for each dimension, in the order Google Ads lists them, with its names.
export const DEMOGRAPHIC_VALUES: Record<DemographicDimension, readonly [string, string][]> = {
  AGE_RANGE: [
    ["AGE_RANGE_18_24", "18–24"],
    ["AGE_RANGE_25_34", "25–34"],
    ["AGE_RANGE_35_44", "35–44"],
    ["AGE_RANGE_45_54", "45–54"],
    ["AGE_RANGE_55_64", "55–64"],
    ["AGE_RANGE_65_UP", "65+"],
    ["AGE_RANGE_UNDETERMINED", "Unknown"],
  ],
  GENDER: [
    ["FEMALE", "Female"],
    ["MALE", "Male"],
    ["UNDETERMINED", "Unknown"],
  ],
  PARENTAL_STATUS: [
    ["PARENT", "Parent"],
    ["NOT_A_PARENT", "Not a Parent"],
    ["UNDETERMINED", "Unknown"],
  ],
  INCOME_RANGE: [
    ["INCOME_RANGE_90_UP", "Top 10%"],
    ["INCOME_RANGE_80_90", "11–20%"],
    ["INCOME_RANGE_70_80", "21–30%"],
    ["INCOME_RANGE_60_70", "31–40%"],
    ["INCOME_RANGE_50_60", "41–50%"],
    ["INCOME_RANGE_0_50", "Lower 50%"],
    ["INCOME_RANGE_UNDETERMINED", "Unknown"],
  ],
}

/** Names a value as Google Ads does, such as `Age 18–24`. */
export function demographicName(dimension: DemographicDimension, value: string): string {
  const shown = DEMOGRAPHIC_VALUES[dimension].find(([key]) => key === value)?.[1] ?? value
  return `${DIMENSION_NAMES[dimension]} ${shown}`
}
