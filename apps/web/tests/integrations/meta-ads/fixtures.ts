export function insightsData(overrides: Record<string, unknown> = {}) {
  return {
    rows: [insightsRow()],
    row_count: 1,
    truncated: false,
    truncation_note: null,
    mode: "direct",
    notes: [],
    currency: "EUR",
    timezone_name: "Europe/Paris",
    level: "campaign",
    since: "2026-09-01",
    until: "2026-09-07",
    ...overrides,
  }
}

export function insightsRow(overrides: Record<string, unknown> = {}) {
  return {
    keys: { campaign_name: "Example campaign", campaign_id: "123" },
    metrics: { spend: 125.5, ctr: 0.5, impressions: 4000, cpc: null },
    actions: {
      actions: [{ action_type: "purchase", value: 3, windows: { "1d_click": 2, "7d_click": 3 } }],
      action_values: [{ action_type: "purchase", value: 450, windows: {} }],
    },
    date_start: "2026-09-01",
    date_stop: "2026-09-07",
    ...overrides,
  }
}

export function accountEntry(data: unknown, overrides: Record<string, unknown> = {}) {
  return {
    provider_key: "meta_ads",
    display_name: "Example ad account",
    external_id: "123",
    status: "success",
    data,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}
