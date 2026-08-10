// apps/web/src/integrations/google_ads/presenters/negative-keywords/index.tsx

import type { ToolRowPresenter } from "@/integrations/contract"
import { googleAdsAdGroupNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/ad-group"
import { googleAdsCampaignNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/campaign"
import { googleAdsListNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/list"

export { googleAdsCampaignNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/campaign"
export { googleAdsListNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/list"

export const googleAdsNegativeKeywordsPresenters: ToolRowPresenter[] = [
  googleAdsListNegativeKeywordsPresenter,
  googleAdsCampaignNegativeKeywordsPresenter,
  googleAdsAdGroupNegativeKeywordsPresenter,
]
export { googleAdsAdGroupNegativeKeywordsPresenter } from "@/integrations/google_ads/presenters/negative-keywords/ad-group"
