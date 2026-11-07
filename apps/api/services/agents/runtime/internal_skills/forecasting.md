---
name: forecasting
human_name: Forecasting
description: Use when someone asks you to forecast, project, or predict a series over time, such as sales, orders, sign-ups, traffic, or spend, from a file, spreadsheet, or ad or analytics report. Covers gathering and lining up the history, choosing the frequency, adding holidays and planned events, when not to forecast, and explaining the range and accuracy.
---

# Forecasting

Use this guide when someone wants to know what a number is likely to do next:
orders over the next eight weeks, sign-ups next quarter, or traffic through
the holidays. `forecast_series` runs Timestral 123M, a forecasting model, on
the history you send. It returns a likely value and range for each future
period, a test of how accurate it was on the end of the history, and the
public holidays in the forecast period. The conversation shows the result as
a forecast card with a chart, so you don't need to draw one.

The person you work with usually isn't a statistician. They want a number
they can plan with, how far to trust it, and what could move it.

## What a forecast can and can't answer

A forecast answers "what's likely to happen if things carry on as they
are, plus the events we already know about?"

It doesn't answer "what would happen if we doubled spend?" or "how much did
the promo cause?". Those are what-if and cause-and-effect questions. If
someone asks one, say a forecast can't answer it. You can still forecast with
their planned changes included as covariates, as long as you describe the
result as a forecast under that plan, not as the effect of the plan.

## Tools

| Task | Tool |
| --- | --- |
| Read history from a CSV file, spreadsheet, or saved report | `read_table` |
| Pull history from a connected ad or analytics account | That provider's report tool |
| Line up dates, total by period, and build covariates | `run_code` |
| Forecast one series | `forecast_series` |

`forecast_series` works directly or inside a `run_code` script. When the
history needs reading, totalling by period, or lining up with other data,
do all of it in one script and call `forecast_series` at the end. When the
history is already a clean list of values in the conversation, call it
directly.

The tool forecasts one series per call. To forecast several, such as each
region, call it once per series.

## Gather the history

1. Use real history only. Never invent, extend, smooth, or fill in values.
   If a period is missing, send `null` for it. Send `0` only when the value
   really was zero, such as a day the shop was closed.
2. Read every row. A preview shows only the first rows; page through the
   whole table with `read_table` before you total anything.
3. Sort by date, and give one value per period with no skipped periods. If
   the source skips days with no sales, add those days back as `0` or `null`
   depending on what the gap means. Ask if you can't tell.
4. Total or average rows that share a period, such as several orders on one
   day or several campaigns in one week. Use a total for counts and money,
   and an average for rates and prices.
5. Use as much history as you have, up to the tool's limit. A year or more
   lets the model learn seasonal patterns.
6. Leave out the current period if it isn't over yet. A half-finished week
   looks like a sudden drop.

## Choose the frequency

- Match the frequency to the decision: daily for staffing and stock, weekly
  for most planning, monthly for budgets.
- Forecast at the frequency of the data when it's already daily or weekly.
  Daily history gives the model the most to learn from, and holidays fall on
  exact days.
- Use weekly or monthly when daily values are mostly zero or very noisy, or
  when daily history would run past the history limit.
- Convert the person's horizon to periods: eight weeks is `horizon=56` daily
  or `horizon=8` weekly. A quarter is about 13 weeks or 91 days.
- `start` is the first history period: a date for daily, the first day of the
  first week for weekly, the first of the month for monthly, and a date and
  hour for hourly.

## Add what's known in advance

Holidays and planned events often explain more than the history alone.

- **Public holidays:** set `holiday_regions` to the markets the business
  sells in: `uk`, `eu`, `us`, or `au`. Each one becomes the share of that
  region's population on a public holiday each day, so regional holidays,
  such as Scotland's 2 January, count partly.
- **Retail events aren't public holidays.** Black Friday, Cyber Monday,
  Mother's Day, Prime Day, and sale weekends need their own `known_future`
  covariate, with `1` on those days and `0` otherwise.
- **Known-future covariates** are values you know for the history and the
  forecast period: promo days, planned ad spend, price changes, store
  openings, school terms, or a weather forecast for the next few days. Their
  values cover the history and then the horizon, so they have history plus
  horizon values.
- **Past-only covariates** are values you know only for the history, such as
  site traffic or competitor prices. They have one value per history period.
- Use `kind="category"` for labels, such as campaign type or store format.
- Ask about planned events if the person hasn't mentioned any and the
  forecast period includes a likely sale, launch, or price change.
- Only add covariates you have real values for. A planned-spend covariate
  with guessed future spend makes the forecast look more certain than it is.

## When not to forecast

- **Too little history.** The tool needs at least twice the horizon, and at
  least 16 periods. Three times the horizon or more is better; with less the
  result carries a caveat. When there isn't enough, offer a shorter horizon or
  a coarser frequency instead of a weak forecast.
- **A recent break.** If the business changed recently, such as a new
  product line, a big price change, a site relaunch, or tracking that changed,
  history from before the change describes a different business. Say so, and
  either forecast from the history since the change, if there's enough, or
  explain why a forecast would mislead.
- **Mostly gaps.** The tool refuses history that's more than 30% missing.
- **A one-off target.** A forecast extends patterns. It can't predict a
  launch with no history or a single unusual event.

## Explain the result

Lead with the outcome in the person's units, then the range, then how far to
trust it:

> Expect about 4,100 orders a week through Christmas, likely between 3,600
> and 4,700. When tested on the last eight weeks, it was within 9% on average,
> and allowing for bank holidays cut the error by 31%.

- **Always give the range, not only the middle figure.** `low` and `high`
  are the 10th and 90th percentiles: about eight in ten periods should land
  between them.
- **Give the typical error.** `backtest.typical_error` is the average miss as
  a share of the actual values when the model forecast the last
  `backtest.periods` periods from what came before them. Say it as a
  percentage: 0.09 is "within 9% on average".
- **Mention range coverage when it's off.** `backtest.range_coverage` is the
  share of those actuals inside the range. Well below 0.8 means the range is
  too narrow, so tell the person to expect more variation.
- **Say whether the extra data helped.** A negative
  `backtest.covariate_error_change` means holidays and covariates made the
  forecast more accurate; -0.31 is "cut the error by 31%". A positive value
  means they didn't help.
- **Name the holidays** in the forecast period that the forecast allows for.
- **Pass on the caveat** when the result has one.
- Add up periods the way the person thinks about them. If they asked about
  weeks, total the daily medians, lows, and highs in a script and report weekly
  figures. Totals of daily lows and highs are wider than the true weekly
  range, so call them a cautious range.
- Use plain words: "likely range", "typical error", and "tested on the last
  eight weeks". Avoid "quantile", "WAPE", and "covariate" unless the person
  uses them.
