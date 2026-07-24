import { describe, expect, it } from "vitest"

import { chartSpec } from "@/features/conversations/native-tools/chart-tool"

const COMPACT_SPEC = {
  chart_type: "line",
  title: "Weekly revenue",
  x_axis: {
    data_key: "week",
    format: "date",
    tick_angle: -35,
  },
  series: [
    {
      data_key: "revenue",
      label: "Revenue",
      format: "currency",
      currency_code: "GBP",
    },
  ],
  data: [
    { week: "2026-07-06", revenue: "1250.5" },
    { week: "2026-07-13", revenue: 1810 },
    { week: "2026-07-20" },
  ],
}

describe("chartSpec", () => {
  it("fills renderer defaults for a compact agent-produced chart", () => {
    const parsed = chartSpec(COMPACT_SPEC)

    expect(parsed?.title).toBe("Weekly revenue")
    expect(parsed?.y_axes).toHaveLength(1)
    expect(parsed?.y_axes[0]?.id).toBe("primary")
    expect(parsed?.series[0]?.y_axis_id).toBe("primary")
    expect(parsed?.series[0]?.color).toBeNull()
    expect(parsed?.data).toEqual([
      { week: "2026-07-06", revenue: 1250.5 },
      { week: "2026-07-13", revenue: 1810 },
      { week: "2026-07-20", revenue: null },
    ])
    expect(parsed?.options.show_legend).toBe(true)
    expect(parsed?.x_axis.tick_angle).toBe(-35)
  })

  it("accepts named secondary axes and explicit brand hex colors", () => {
    const parsed = chartSpec({
      ...COMPACT_SPEC,
      chart_type: "composed",
      y_axes: [
        { id: "money", label: "Revenue", format: "currency", currency_code: "GBP" },
        { id: "rate", label: "Conversion", format: "percent", orientation: "right" },
      ],
      series: [
        {
          data_key: "revenue",
          label: "Revenue",
          kind: "bar",
          y_axis_id: "money",
          color: "#123456",
        },
        {
          data_key: "conversion",
          label: "Conversion",
          kind: "line",
          y_axis_id: "rate",
          color: "#FEDCBA",
          curve: "step",
          connect_nulls: true,
          show_points: true,
          line_style: "dashed",
        },
      ],
      data: [{ week: "2026-07-06", revenue: 1250.5, conversion: 18.2 }],
    })

    expect(parsed?.y_axes).toHaveLength(2)
    expect(parsed?.series[1]?.y_axis_id).toBe("rate")
    expect(parsed?.series[1]?.color).toBe("#FEDCBA")
    expect(parsed?.series[1]).toMatchObject({
      connect_nulls: true,
      curve: "step",
      line_style: "dashed",
      show_points: true,
    })
  })

  it("unwraps a named spec argument when a transport preserves the parameter name", () => {
    expect(chartSpec({ spec: COMPACT_SPEC })?.title).toBe("Weekly revenue")
  })

  it("rejects malformed load-bearing fields", () => {
    expect(chartSpec({ ...COMPACT_SPEC, chart_type: "script" })).toBeNull()
    expect(chartSpec({ ...COMPACT_SPEC, series: [] })).toBeNull()
    expect(chartSpec({ ...COMPACT_SPEC, data: [{ week: "2026-07-06", revenue: [] }] })).toBeNull()
    expect(chartSpec({ ...COMPACT_SPEC, options: { animation: true } })).toBeNull()
    expect(
      chartSpec({
        ...COMPACT_SPEC,
        series: [{ ...COMPACT_SPEC.series[0], stroke_dasharray: "1 1" }],
      })
    ).toBeNull()
  })

  it("matches backend decimal coercion and rejects JavaScript-only numeric strings", () => {
    expect(
      chartSpec({
        ...COMPACT_SPEC,
        data: [{ week: "2026-07-06", revenue: "0x10" }],
      })
    ).toBeNull()
    expect(
      chartSpec({
        ...COMPACT_SPEC,
        data: [{ week: "2026-07-06", revenue: "Infinity" }],
      })
    ).toBeNull()
    expect(
      chartSpec({
        ...COMPACT_SPEC,
        data: [{ week: "2026-07-06", revenue: "1.25e3" }],
      })?.data[0]?.["revenue"]
    ).toBe(1250)
  })
})
