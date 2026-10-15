// apps/web/src/integrations/meta_ads/lib/objectives.ts

// Keyed as the server's objective table in apps/api/integrations/meta_ads/tools/schemas/campaigns.py.
export const OBJECTIVE_KEYS = [
  "sales",
  "leads",
  "traffic",
  "engagement",
  "awareness",
  "app_promotion",
] as const

export type Objective = (typeof OBJECTIVE_KEYS)[number]

export const OBJECTIVE_SENTENCES: Record<Objective, string> = {
  sales: "Sales: get purchases on your website or app.",
  leads: "Leads: get contact details from people interested in your business.",
  traffic: "Traffic: send people to your website or app.",
  engagement: "Engagement: get more likes, comments, shares, and messages.",
  awareness: "Awareness: show your ads to as many people as possible.",
  app_promotion: "App promotion: get people to install your app.",
}
