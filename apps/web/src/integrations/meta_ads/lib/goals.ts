// apps/web/src/integrations/meta_ads/lib/goals.ts

import type { Objective } from "@/integrations/meta_ads/lib/objectives"

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
export type GoalAsset = "page" | "pixel" | "app"

export const GOALS: Record<
  Goal,
  {
    label: string
    description: string
    objective: Objective
    asset: GoalAsset | null
    clicksBilling: boolean
  }
> = {
  reach: {
    label: "Reach",
    description: "Show the ads to as many different people as possible.",
    objective: "awareness",
    asset: "page",
    clicksBilling: false,
  },
  impressions: {
    label: "Impressions",
    description: "Show the ads as many times as possible.",
    objective: "awareness",
    asset: "page",
    clicksBilling: false,
  },
  ad_recall_lift: {
    label: "Ad Recall Lift",
    description: "Reach people likely to remember the ads.",
    objective: "awareness",
    asset: "page",
    clicksBilling: false,
  },
  link_clicks: {
    label: "Link Clicks",
    description: "Get as many clicks to your website as possible.",
    objective: "traffic",
    asset: null,
    clicksBilling: true,
  },
  landing_page_views: {
    label: "Landing Page Views",
    description: "Get people to your website who wait for it to load.",
    objective: "traffic",
    asset: null,
    clicksBilling: false,
  },
  post_engagement: {
    label: "Post Engagement",
    description: "Get likes, comments, and shares on the ads.",
    objective: "engagement",
    asset: null,
    clicksBilling: false,
  },
  page_likes: {
    label: "Page Likes",
    description: "Get more likes for your Page.",
    objective: "engagement",
    asset: "page",
    clicksBilling: false,
  },
  app_installs: {
    label: "App Installs",
    description: "Get people to install your app.",
    objective: "app_promotion",
    asset: "app",
    clicksBilling: false,
  },
  website_conversions: {
    label: "Website Conversions",
    description: "Get people to take an action on your website, such as buying.",
    objective: "sales",
    asset: "pixel",
    clicksBilling: false,
  },
}

export const ASSET_LABELS: Record<GoalAsset, string> = {
  page: "Facebook Page",
  pixel: "Pixel",
  app: "App",
}

export const CONVERSION_EVENT_LABELS: Record<string, string> = {
  PURCHASE: "Purchase",
  LEAD: "Lead",
  COMPLETE_REGISTRATION: "Complete Registration",
  ADD_TO_CART: "Add to Cart",
  INITIATED_CHECKOUT: "Initiate Checkout",
  CONTENT_VIEW: "View Content",
  SEARCH: "Search",
  SUBSCRIBE: "Subscribe",
  START_TRIAL: "Start Trial",
  CONTACT: "Contact",
}
