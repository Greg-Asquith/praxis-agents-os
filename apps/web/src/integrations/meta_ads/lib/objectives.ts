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

export const OBJECTIVES: Record<Objective, { label: string; description: string }> = {
  sales: { label: "Sales", description: "Get purchases on your website or app." },
  leads: { label: "Leads", description: "Get contact details from interested people." },
  traffic: { label: "Traffic", description: "Send people to your website or app." },
  engagement: { label: "Engagement", description: "Get likes, comments, shares, and messages." },
  awareness: { label: "Awareness", description: "Show your ads to as many people as possible." },
  app_promotion: { label: "App Promotion", description: "Get people to install your app." },
}
