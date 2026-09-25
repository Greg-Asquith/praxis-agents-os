export function accountData(overrides: Record<string, unknown> = {}) {
  return {
    name: "Shop account",
    status: "Active",
    disable_reason: null,
    currency: "EUR",
    timezone_name: "Europe/Paris",
    amount_spent: "125.50",
    spend_cap: "1000",
    spend_cap_remaining: "874.50",
    balance: "10",
    min_daily_budget: "1",
    ...overrides,
  }
}
export function objectRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "101",
    name: "Summer campaign",
    status: "PAUSED",
    effective_status: "PAUSED",
    objective: "OUTCOME_SALES",
    optimization_goal: null,
    bid_strategy: "LOWEST_COST_WITHOUT_CAP",
    start_time: "2026-09-01T00:00:00+00:00",
    end_time: null,
    campaign_id: null,
    adset_id: null,
    budget: { kind: "daily", amount: "15.50", remaining: "100" },
    bid_amount: null,
    ...overrides,
  }
}
export function objectsData(overrides: Record<string, unknown> = {}) {
  return {
    object_type: "campaign",
    objects: [objectRow()],
    object_count: 1,
    truncated: false,
    currency: "EUR",
    ...overrides,
  }
}
export function conversionRow(overrides: Record<string, unknown> = {}) {
  return {
    id: "901",
    name: "Qualified lead",
    description: "A completed enquiry",
    is_archived: false,
    is_unavailable: false,
    ...overrides,
  }
}
export function conversionsData(overrides: Record<string, unknown> = {}) {
  return {
    conversions: [conversionRow()],
    conversion_count: 1,
    truncated: false,
    notes: [],
    ...overrides,
  }
}
export function customAction(overrides: Record<string, unknown> = {}) {
  return {
    action_type: "offsite_conversion.custom.901",
    custom_conversion_id: "901",
    custom_conversion_name: "Qualified lead",
    value: 3,
    windows: { "1d_click": 2 },
    breakdowns: { action_device: "mobile" },
    ...overrides,
  }
}
