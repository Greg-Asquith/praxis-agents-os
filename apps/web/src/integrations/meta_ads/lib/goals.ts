// apps/web/src/integrations/meta_ads/lib/goals.ts

// Keyed as the server's goal table in apps/api/integrations/meta_ads/goals.py.
export const GOAL_KEYS = [
  "reach",
  "impressions",
  "ad_recall_lift",
  "link_clicks",
  "landing_page_views",
  "post_engagement",
  "page_likes",
  "app_installs",
  "website_conversions",
] as const

export type Goal = (typeof GOAL_KEYS)[number]

const GOAL_SENTENCES: Record<Goal, (asset: string | null) => string> = {
  reach: (page) => `Show ads to as many people as possible, as the Page ${page ?? "chosen"}`,
  impressions: (page) => `Show ads as many times as possible, as the Page ${page ?? "chosen"}`,
  ad_recall_lift: (page) =>
    `Reach people likely to remember the ads, as the Page ${page ?? "chosen"}`,
  link_clicks: () => "Get clicks to your website",
  landing_page_views: () => "Get people to your website who wait for it to load",
  post_engagement: () => "Get likes, comments, and shares on the ads",
  page_likes: (page) => `Get likes for the Page ${page ?? "chosen"}`,
  app_installs: (app) => `Get installs of the app ${app ?? "chosen"}`,
  website_conversions: (pixel) =>
    `Get conversions on your website, measured by your pixel ${pixel ?? "chosen"}`,
}

export const CONVERSION_EVENT_LABELS: Record<string, string> = {
  PURCHASE: "Purchase",
  LEAD: "Lead",
  COMPLETE_REGISTRATION: "Complete registration",
  ADD_TO_CART: "Add to cart",
  INITIATED_CHECKOUT: "Initiate checkout",
  CONTENT_VIEW: "View content",
  SEARCH: "Search",
  SUBSCRIBE: "Subscribe",
  START_TRIAL: "Start trial",
  CONTACT: "Contact",
}

export function goalSentence(goal: Goal, asset: string | null, event: string | null): string {
  const sentence = GOAL_SENTENCES[goal](asset)
  return event ? `${sentence} (${event}).` : `${sentence}.`
}
