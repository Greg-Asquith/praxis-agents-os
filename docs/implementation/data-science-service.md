<!-- docs/implementation/data-science-service.md -->

# Data science service

The data science service runs CPU-sized models and numeric libraries in an
isolated container. Its first operation is `forecast`, which runs Mistral's
Timestral 123M model. The service never runs model-authored code: agents
write code only through `run_code`.

The `forecast_series` tool calls it (see [below](#forecast_series-tool)).
The tool is hidden when `DATA_SCIENCE_URL` is unset.

## Layout

`apps/data-science/` is its own service, a peer of `apps/media-renderer/`. It
shares only the isolation driver in `apps/isolation-driver/`, which its
Dockerfile copies from a named build context
(`--build-context driver=apps/isolation-driver`, or `additional_contexts` in
Compose). See [Video tools](video-tools.md#media-renderer) for the driver.

| Path | Role |
|---|---|
| `datascience/__main__.py` | Starts the driver with a 4 MiB request cap, no transfers, and the forecast self-check |
| `datascience/operations.py` | The `OPERATIONS` the service offers |
| `datascience/forecast.py` | Validates a forecast request and runs it in a child; standard library only |
| `datascience/child_forecast.py` | The isolated child: holiday covariates, Timestral, backtest metrics |
| `datascience/holidays_calendar.py` | Population-weighted public holiday shares |
| `datascience/population_weights.json` | Population per holiday calendar, with source and reference date |
| `datascience/self_check.py` | One tiny forecast through the real operation before serving |
| `pyproject.toml`, `uv.lock` | CPU-only PyTorch, Timestral (pinned Git commit), `holidays`, NumPy, all hash-pinned |

## Image

- Python 3.12 slim (trixie). The code and the virtual environment are owned
  by root; the service runs as user 1001.
- PyTorch comes from the PyTorch CPU wheel index. `uv.lock` pins every
  package by hash, including Timestral's Git commit.
- The build downloads Timestral-123M's `model.safetensors`, `config.json`,
  and `LICENSE` from a pinned Hugging Face revision and checks each against
  a pinned SHA-256. They live in `/opt/models/timestral-123m`. The weights'
  licence (Modified MIT) ships beside them.
- `HF_HUB_OFFLINE=1` is set. The child also sets it, loads the weights from
  the local directory only, and has no network because the seccomp filter
  allows only `AF_UNIX` sockets.

## Driver options

The data science service calls `serve` with three options that the media
renderer leaves at their defaults:

- `max_request_bytes=4 MiB`: series travel inline in the request. The media
  renderer keeps 64 KiB.
- `transfers=False`: the service fetches and uploads nothing. Start-up
  refuses `RENDERER_ALLOWED_URL_PREFIXES`, so no URL is ever allowed. Every
  operation declares zero inputs and zero outputs.
- `ready_check=check_forecast`: after the isolation self-check, one tiny
  forecast runs in an isolated child through the real operation. It proves
  PyTorch works under the seccomp filter and limits, and that the weights
  load offline. If it fails, the service exits before serving.

The driver settings it reads are `RENDERER_MAX_TIMEOUT_SECONDS`,
`RENDERER_CHILD_MEMORY_BYTES`, and optionally `RENDERER_SHARED_SECRET`.
PyTorch and the weights need about 3 GiB of child address space; 2 GiB fails
while loading the weights.

## Forecast operation

One request runs one forecast:

```json
{
  "operation": "forecast",
  "timeout_seconds": 120,
  "inputs": [],
  "outputs": [],
  "arguments": {
    "start": "2025-11-03",
    "frequency": "daily",
    "values": [212.4, 198.0, null, 240.1],
    "horizon": 56,
    "holiday_regions": ["uk", "eu"],
    "covariates": [
      {"timing": "known_future", "kind": "number", "values": [0, 0, 1, 0]}
    ]
  }
}
```

### Arguments

| Field | Rule |
|---|---|
| `start` | ISO date, or date and time for `hourly`. No time zone. The first of a month for `monthly`. Every period must fall between 1950 and 2100. |
| `frequency` | `hourly`, `daily`, `weekly`, or `monthly` |
| `values` | Up to 32,768 finite numbers or `null` for a gap. At least `max(16, 2 × horizon)` points, and at most 30% gaps. |
| `horizon` | 1 to 1,024 steps |
| `holiday_regions` | Each of `uk`, `eu`, `us`, `au` at most once |
| `covariates` | Up to eight. `timing` is `known_future` (values cover history plus horizon) or `past_only` (history only). `kind` is `number`, or `category` with whole-number codes. |

Covariates carry no names: the API keeps names and category labels and sends
only numbers. Any other field, type, or non-finite number is refused with
`invalid_request` before a child starts.

### What the child computes

The child builds one known-future covariate per holiday region, then runs:

- the forecast with every covariate
- a backtest that holds out the last `min(horizon, history // 4)` points and
  forecasts them from the rest
- when there are covariates, the same forecast and backtest without them

Timestral's defaults apply: symmetric averaging and clipping at zero for
series with no negative values. Each result series has the median and the
0.1 and 0.9 quantiles. The backtest also reports, over the observed held-out
values:

- `wape`: `sum |actual − median| / sum |actual|`
- `coverage`: the share of actuals inside the 10 to 90% band
- `quantile_loss`: weighted quantile loss over all 21 quantile levels

`quantile_loss_change` is the relative change in quantile loss from adding
covariates. Negative means covariates lowered the error.

### Result

```json
{
  "forecast": {"median": [], "low": [], "high": []},
  "baseline": {"median": [], "low": [], "high": []},
  "backtest": {
    "holdout": 56,
    "forecast": {"median": [], "low": [], "high": [], "wape": 0.09, "coverage": 0.82, "quantile_loss": 0.07},
    "baseline": {"median": [], "low": [], "high": [], "wape": 0.13, "coverage": 0.75, "quantile_loss": 0.10},
    "quantile_loss_change": -0.31
  },
  "holiday_covariates": {"uk": [], "eu": []},
  "holidays": [{"date": "2026-12-25", "region": "uk", "name": "Christmas Day", "share": 1.0}]
}
```

`baseline` fields are `null` when there are no covariates. The driver checks
every series' length and that every number is finite before returning the
result. A child that crashes returns `forecast_failed`; one killed by a limit
returns `resource_limit`; a series Timestral can't forecast returns
`invalid_series`.

## Holiday covariates

Each region's value for a day is the share of its population on a public
holiday, from 0 to 1. Weekly and monthly periods sum their days, so a week
with Christmas and Boxing Day scores about 2. An hour uses its calendar date.

The `holidays` library supplies the calendars with `observed=True` and the
`PUBLIC` category, so both the actual and the observed day count. Names are
in English (`en_US`); a day's name comes from the largest calendar that
observes it.

| Region | Calendars | Weights |
|---|---|---|
| `uk` | GB subdivisions ENG, NIR, SCT, WLS | ONS mid-2025 estimates (Nomis `NM_2002_1`) |
| `eu` | The 27 member states, national holidays only | Eurostat `tps00001`, 1 January 2026 |
| `us` | Federal holidays, one calendar | Weight 1 |
| `au` | National plus ACT, NSW, NT, QLD, SA, TAS, VIC, WA | ABS estimated resident population, 2026 Q1 |

Retail events such as Black Friday aren't public holidays. Agents add them as
their own `known_future` covariates. Governments declare one-off holidays, so
bump `holidays` with dependency audits.

## Performance

On 2 CPUs, a daily series of one year with a 56-day horizon and two regions
takes about 2.5 seconds, mostly loading PyTorch and the weights. The largest
request the API will send (10,000 hourly points, a 1,024-step horizon, four
regions, and eight covariates) takes about 75 seconds, so the default timeout
is 300 seconds.

## `forecast_series` tool

`apps/api/services/agents/runtime/tools/forecasting.py` defines
`forecast_series`. It's a read-only `core` tool that every agent mounts when
the service is configured, and it's code-eligible, so a `run_code` script can
line data up and forecast it in one step. It takes `title`, optional `unit`,
`start`, `frequency`, `values`, `horizon`, `holiday_regions`, and
`covariates` (`name`, `timing`, `kind`, `values`).

Before calling the service, the tool refuses with a plain retry message:

- more than `FORECAST_MAX_HISTORY_POINTS` history points (10,000)
- a horizon over `FORECAST_MAX_HORIZON` (1,024)
- more than `FORECAST_MAX_COVARIATES` covariates (8)
- fewer than `max(16, 2 × horizon)` history points, or more than 30% gaps
- a covariate whose length misses the history (and the horizon, for
  `known_future`), or a number covariate that holds text

Category labels become codes in first-seen order; names and labels stay in
the API. The service's own `invalid_request` message is returned as a retry.
`invalid_series` becomes a plain failure saying Timestral couldn't forecast
the series. Any other error, or a result whose series don't fit the request,
fails the call.

### Client

`services/data_science/run_forecast.py` posts the operation with
`timeout_seconds` set to `DATA_SCIENCE_TIMEOUT_SECONDS` and validates the
result's shape and every series' length. The HTTP post, the auth header
(`google_id_token` with the service URL as audience, `shared_secret`, or
`none` locally), and error mapping live in `apps/api/utils/isolated_service.py`,
which the media renderer client also uses. `DATA_SCIENCE_AUTH=none` is
refused outside `ENVIRONMENT=local`, and a shared secret must be at least 32
characters.

### Result

The model sees:

- `forecast`: one row per period (`period`, `median`, `low`, `high`), rounded
  to the most decimal places in the history, up to six
- `backtest`: `periods` held out, `typical_error` (WAPE), `range_coverage`
  (share of actuals in the 10 to 90% range), and `covariate_error_change`
  (relative change in quantile loss; negative means covariates helped)
- `holidays` in the horizon, with region and population share
- `caveat` when the history is less than three horizons, plus `method`,
  `frequency`, and `history_points`

The forecast card gets the same value plus `chart` through `public_result`
metadata, which never reaches the model or a script. `chart` holds the
period labels and history for the last `max(3 × horizon, 90)` periods, both
forecasts (with and without covariates), both backtests, and each covariate
(holiday regions first) over the same window. The largest request yields
about 600,000 characters, within the declared 1,000,000.

### Forecast card

`forecast-tool-presenter.tsx` renders `forecast_series` rows in
conversations and on nested `run_code` calls. Running calls show a collapsed
loading card. Failed calls, and results whose `chart` doesn't parse, fall back
to the default row.

- The main chart shows history as a neutral line, the median as a
  `--chart-1` line, and the 10 to 90% range as a shaded band. A reference
  line marks where the forecast starts, and faint lines mark holidays in the
  horizon. The tooltip names them.
- Covariate strips sit under the chart on the same X axis, holiday regions
  first.
- When `baseline` exists, one **Use in Forecast** switch swaps in the
  forecast without covariates on the client. It never re-runs the tool. With
  the switch on, the header shows the backtest's `covariate_error_change`.
- The footer gives the typical error and range coverage. With covariates off,
  the card scores the no-covariate backtest from `chart` itself.
- **PNG** and **SVG** export the main chart through `lib/chart-export.ts`,
  which `build_chart` cards also use.

### Forecasting skill and evals

The internal skill `runtime/internal_skills/forecasting.md` holds the longer
working rules: what a forecast can't answer, gathering and lining up history
without inventing values, choosing the frequency and horizon, holiday regions
and `known_future` covariates (retail events such as Black Friday aren't
public holidays), when not to forecast, and explaining the range, typical
error, and covariate change in plain words. Update it when the tool's
arguments, limits, or result change.

The `forecast_*` cases in `apps/api/evals/datasets/agent_behavior.yaml` check
that an agent forecasts a read CSV once with the right frequency, horizon, and
holiday region and the history unchanged, and that it reports the range and
backtest error. They need `DATA_SCIENCE_URL`; see the
[evals README](../../apps/api/evals/README.md).

## Local development

To run it by hand:

```bash
docker compose --profile data-science up -d --build data-science
```

It listens on `127.0.0.1:8091` (override with `PRAXIS_DATA_SCIENCE_PORT`),
runs as user 1001 with a 4 GiB memory limit, and logs
`{"message": "renderer ready", "isolation": "verified"}` once both
self-checks pass. `make dev` starts it when `apps/api/.env` sets
`DATA_SCIENCE_URL` (use `http://127.0.0.1:8091` with `DATA_SCIENCE_AUTH=none`).

## Deployment

On GCP, `praxis-data-science` is a Cloud Run gen2 service with one request
per instance, 2 vCPU, 4 GiB, startup CPU boost, and scale to zero. It runs as
its own service account with no roles. Only the API and worker identities
hold `run.invoker`, and the deploy reads the policy back. The deploy passes
`DATA_SCIENCE_URL`, `DATA_SCIENCE_TIMEOUT_SECONDS`, and the three
`FORECAST_MAX_*` limits to the API and worker. See
[GCP deployment](../../deploy/gcp/README.md#data-science-service).

## Verification

`make datascience-check` builds the `test` image target and runs it on Linux
in Docker:

- validation refuses a known-future covariate that misses the horizon, too
  short a history, and a non-finite value
- a weekly pattern forecasts within tolerance through the full driver path,
  with its band around the median
- holiday shares for Scotland's 2 January, EU Christmas, Victoria's Melbourne
  Cup, and a UK December month
- start-up fails when the weights are missing

`make isolation-driver-check` covers zero-input operations and the
per-service request cap.

In the API, `tests/services/agents/runtime/test_forecasting_tool.py` uses a
stub transport: the tool is hidden without the service, labels and the chart
stay out of the request and the model's result, a short known-future
covariate is refused before any request, and a malformed result fails.
`tests/scenarios/test_forecasting.py` forecasts from a `run_code` script and
checks the nested audit record and that the chart never reaches the model.
