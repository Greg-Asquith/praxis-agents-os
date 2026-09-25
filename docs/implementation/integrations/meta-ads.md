# Meta Ads integration

Meta Ads connects a workspace to the ad accounts assigned to an agency's Meta
system user. Discovered accounts can join active context and Context Groups.
Agents can run bounded Insights reports on selected accounts. Account overview,
object listing, change history, writes, Facebook sign-in, and event delivery
are pending.

Backend code lives in `apps/api/integrations/meta_ads/`; the web module lives in
`apps/web/src/integrations/meta_ads/`. The provider uses the shared API-key
connection and secret-reference path with a field labelled **Access token**.
Connections belong to the workspace, not an individual user.

## Set up the agency's app

Use one agency-owned app for each deployment. Complete this setup in Meta:

1. In the agency's business portfolio, create a Meta app and add the Marketing
   API product. Record its mode and permission access levels.
2. Have each client share its ad account and Page with the agency's business
   portfolio as a partner.
3. In **Business Settings > Users > System users**, create or select a system
   user and assign the accounts. Grant **Manage campaigns** for management or
   **View performance** for reporting. Assign **Advertise** on the Pages.
4. Generate a System User access token for the agency's app. Select **Never**
   for expiry and request the permissions listed below.
5. In the deployment, add `meta_ads` to `INTEGRATIONS_ENABLED_PROVIDERS`.
6. In Praxis **Integrations**, connect Meta Ads and paste the token into
   **Access token**. Select the discovered accounts for the intended context.

The setup requests these permissions:

| Permission | Intended use |
| --- | --- |
| `ads_read` | Ad account reporting |
| `ads_management` | Ad account management; required for writable discovery |
| `business_management` | Business asset access |
| `pages_show_list` | Page discovery for later ad workflows |
| `pages_manage_ads` | Page advertising for later ad workflows |
| `pages_read_engagement` | Page data for later ad workflows |

Page resources and agent operations remain pending. An empty discovery result
is valid: assign accounts to the system user, then select **Rediscover**.
Adding accounts does not require replacing the token if its permissions remain
sufficient. The connection label is the label entered in Praxis.

The intended agency setup uses a development-mode app with standard permission
access. Partner-account and Page access without App Review or Business
Verification is an accepted implementation assumption, not a verified result.
If the agency's app cannot use its partner assets, revisit this setup before
relying on it. Personal user tokens and token renewal are unsupported.

## Configure app-secret proof

`META_ADS_APP_ID` is optional deployment metadata. `META_ADS_APP_SECRET` is
optional; unset and blank values both disable proof generation. Store the
agency's app secret in the deployment's secret store and enable **Require App
Secret** in that same Meta app when using this protection.

For every request with a non-empty secret, the client computes
`appsecret_proof` as hex-encoded HMAC-SHA256 of the resolved access token,
using the app secret as the key. Tokens travel only in the bearer header.
Proofs travel in the query string, so provider HTTP diagnostics are suppressed
and error details redact credentials and proofs. Discovery and credential-based
client helpers use the same deployment secret.

All pasted tokens must come from that agency app. A Graph error mentioning
`appsecret_proof` produces guidance to use the agency's app when a secret is
configured, or to ask the administrator to add the secret when absent. Exact
live error bodies and subcodes remain unverified; generic permission errors
do not establish an app mismatch.

## Discovery and writability

Discovery reads `/me` for identity, `/me/permissions` for granted permissions,
and `/me/adaccounts` for account data and `user_tasks`. Missing identity fails
with guidance to replace the token. Account discovery requests 100 records per
page, with a 20-page cap. A cap or repeated cursor retains discovered accounts
and marks the connection degraded with `page_cap`.

Pagination accepts only HTTPS URLs on `graph.facebook.com` with the same
versioned path. The client extracts the next cursor and rebuilds the request
with its own bearer token and proof; it does not forward the supplied URL.

Each `meta_ads_ad_account` resource uses its bare numeric account ID. Discovery
deduplicates by ID, sorts by name, and falls back to `Ad account ID`, with the
account ID substituted, when a name is absent. Metadata includes currency,
time zone, the account status label, business ID and name, tasks, and granted
token permissions.

An account is writable only when all these conditions hold:

- Account status is `ACTIVE` (`1`).
- The token has granted `ads_management` permission.
- Account tasks include `MANAGE` or `ADVERTISE`.

Closed (`101`) and pending-closure (`100`) accounts are omitted. Other accounts,
including disabled, unsettled, or unknown statuses, remain read-only. Missing
tasks also keep the account read-only. Rediscovery refreshes these permissions.
The provider declares no OAuth scope requirement: the pasted credential does
not contain an OAuth grant. Write bindings require a writable resource through
the shared active-context resolver.

## Errors and request limits

Provider errors follow the existing integration exceptions and retry policy:

| Graph code | Treatment |
| --- | --- |
| `190` | Authentication failure; replace the expired or revoked token |
| `10`, `200`-`299` | Permission failure; check token grants and asset assignments |
| `4`, `17`, `32`, `613`, `80000`-`80014`, or HTTP 429 | Rate limit; fail without retrying, with the reported wait time when available |
| `1`, `2`, or `is_transient=true` | Transient failure; use the shared bounded retry path |
| `100` and other Graph errors | Validation failure |

Details retain a bounded, validated `fbtrace_id` for support. Insights validation
errors return Meta's bounded message so the agent can correct fields and
breakdown combinations. Credentials and proofs are redacted before errors leave
the client. Usage headers remain in process-local numeric state, outside logs
and audit details. Each process keeps up to 256 account entries. Known account
or Insights utilisation at 100% blocks further Insights requests until the
reported regain time passes. Cooldowns retain separate deadlines for app
Insights, account Insights, business Insights, and account utilisation. A
healthy update clears only its own quota, and a shorter saturated update
cannot shorten its active deadline. An expired restriction cannot be revived
by another quota's reset time. Same-response wait-only account or Insights
business headers can qualify Insights utilisation; healthy quotas and other
business-use-case types cannot. Saturated usage without a usable wait does
not block locally. Malformed usage headers are ignored.

The Marketing API access tier is separate from permission access. In the
agency's App Dashboard, check the Marketing API access tier. If it is
**Limited access**, use the dashboard's **Full access** request flow after
building successful API usage and complete the prerequisites Meta displays.
The initial tier and exact request prerequisites remain unverified for the
agency's app. Do not treat the permission level as evidence of a rate limit.

## Insights reports

`meta_ads_run_insights` reads every selected `meta_ads_ad_account` through the
shared context, authorisation, audit, and retained-result paths. It defaults to
`auto`, supports Code Mode, and has a 150-second timeout. Account failures stay
separate, so another selected account can still return its report. Mixed
success and error results retain every completed report. The tool requests a
whole-call query correction only when every account reports an invalid
Insights query, after recording each failure audit. Authentication failures
remain account errors with connection recovery guidance.

Supply 1-30 field names and absolute `since` and `until` dates in the account
time zone. Select account, campaign, ad set, or ad level. Reports support the
bounded breakdown, filter, sort, and attribution arguments in the tool schema.
`time_increment` accepts `all_days`, `monthly`, or 1-90 days. The default row
limit is 100. `META_ADS_INSIGHTS_MAX_ROWS` defaults to 1,000 and bounds an explicit
limit; it is provider-owned because shared report retrieval uses byte limits.
Pagination reports `truncated` when rows remain or a cursor repeats.

When the agent's policy requires approval, the report card provides date
pickers, a reporting-level selector, and searchable common report fields.
Additional Meta field names remain available for provider validation.
**Advanced options** includes editable report intervals, row limits,
breakdowns, attribution windows, sort order, and filters. Empty attribution
selection uses each ad set's settings. Optional filters can be omitted or
null; filter values retain their scalar or list shape through approval.
Invalid dates and incomplete options show correction guidance on the card.

The frontend reads report choices, defaults, and limits from `form_schema` in
`GET /tools/presentations`. The provider builds this JSON Schema from its
request model, field classification, supported query options, and configured
row limit. The frontend has no duplicate option lists. Missing metadata blocks
approval with reload guidance and leaves **Decline** available. Backend request
validation remains authoritative for field combinations and account-specific
availability.

Rows contain identity, breakdown, and supported text `keys`, numeric `metrics`,
action lists, and report dates. Text fields such as `objective`,
`optimization_goal`, and `quality_ranking` remain plain data, bounded to 512
characters. Missing text and metrics remain null; missing action lists remain
empty lists. Each action retains its action type, value, attribution
windows, and requested device or destination breakdown values. Money metrics
stay in major currency units; Insights spend is never divided by 100. Counts
are integers and rates remain decimal numbers. CTR is percentage points.
Account currency and time zone come from discovery metadata. Missing metadata
is displayed as unavailable rather than inferred.

The provider's `insights_fields.py` classification controls validation,
parameters, and parsing. Action statistics include fields such as
`outbound_clicks`, `video_play_actions`, and `cost_per_outbound_click`, including
when callers set explicit action breakdowns. Known object and histogram fields,
such as `results`, `cost_per_result`, and `video_play_curve_actions`, receive
correction guidance before credentials or reports are read because their
structured shapes are unsupported. Unknown field names still reach Meta for
provider correction; successful unknown scalar metrics use strict numeric
parsing. Invalid numeric values never become text or action lists.
The classification was checked against Meta's
[official SDK field definitions](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adsinsights.py)
on 24 September 2026. The SDK is not a runtime dependency, and these definitions
do not establish field availability for a live account.
To update the picker, review the backend field classification and supported
query options against Meta's API and SDK definitions. The browser receives
those changes through tool metadata. This catalogue is a reviewed snapshot;
it does not synchronise automatically with Meta. The shared frontend test
fixture must match the backend's published form schema.

The implementation applies these reporting rules:

- Dates are limited to 37 months. `unique_*` fields require a start date within
  13 months.
- With breakdowns older than 13 months, `reach`, `frequency`, and `cpp` are
  removed from the request with a result note.
- Attribution uses each ad set's unified setting unless explicit windows are
  requested. Supported windows are `1d_click`, `7d_click`, `28d_click`, `1d_view`,
  and `1d_ev`. The retired `7d_view` and `28d_view` windows produce correction
  guidance.
- Recent report values can change for up to 28 days.

When Meta returns code 100 with subcode 1487534, the operation submits a
background report using the read retry policy. It polls with increasing delays
within `META_ADS_INSIGHTS_POLL_SECONDS`, which defaults to 90 and accepts 1-120.
Only `Job Completed` with 100% completion allows row retrieval. Failed,
skipped, and timed-out jobs return guidance to narrow the report. Report IDs
stay inside the operation; resuming jobs in another tool call is pending.

Direct execution reserves 15 seconds for result delivery and three seconds
per selected account for terminal audits inside the 150-second tool timeout.
The remaining work allowance is shared across accounts: 132 seconds for one
account, down to 75 seconds for the maximum 20 accounts. Credential
resolution, direct reads, submission, retries, polling, and paging all consume
the same allowance.
Sequential accounts use the remaining time. A per-account polling allowance
cannot extend the shared deadline. Once it expires, completed account reports
remain available, while interrupted and unstarted accounts receive
`meta_ads_insights_deadline` errors. Every account outcome passes through the
shared audit runner. Prior audit time also reduces the next account's work
allowance. The audit reserve matches the shared runner's per-account
finalisation bound. External cancellation still stops execution.

Code Mode has a separate cumulative script deadline, 60 seconds by default,
which includes all nested calls and interpreter work. A background report can
outlast that enclosing deadline even within its provider polling allowance.
Script cancellation can discard the whole script result, including earlier
account reports, while completed operation audits remain. Nested partial
result delivery after script cancellation and shared deadline propagation
remain pending. This provider does not change that runtime contract.

Complete bounded results use the shared internal retained-result File path
when they exceed the transcript preview budget. These Files stay outside
ordinary Files discovery. The presenter supports preview expansion and keeps
source truncation separate from preview truncation. Table cells and detail
views use the shared table currency formatter for money, including spend and
social spend, and show CTR in percentage points. ROAS remains a ratio. Provider
names render as plain text.

Audits contain the account target, requested level and dates, field count,
breakdowns, attribution mode, execution mode, and row count. They omit report
rows, filter values, names, raw usage headers, and provider messages.

### Exact account money conversion

The provider's account money helpers accept supported currencies and convert
minor units exactly. They reject fractional minor units, non-finite numbers,
coefficients longer than 256 digits, absolute exponents above 256, and integer
expansion beyond 256 digits before scaling or integer conversion. Conversion
does not depend on Decimal rounding precision and cannot silently underflow
to zero. These helpers are separate from Insights metrics, which already use
major currency units. Account and budget operation callers remain pending.

### Insights qualification

On 24 September 2026, the maintainer extended the existing live-check waiver
to Insights implementation. Known-day spend against Ads Manager, retired
attribution windows, 14-month breakdown retention, background-job timing,
Limited-access headers, and a real throttle response remain unverified.
Deterministic tests exercise the planned contracts; they do not qualify a
live Meta account. Attempts to retrieve the official Insights reference,
breakdowns, and best-practices pages returned HTTP 429. The rules above remain
implementation assumptions until live qualification confirms them.

## Version upgrades

`META_GRAPH_API_VERSION` in `client.py` pins requests to `v26.0`. Before changing
it, review Meta's Marketing API changelog and version lifecycle, update the
constant, and run the provider and integration contract tests. Repeat live
identity, permission, discovery, and app-secret checks with designated test
assets. Record the tested version and its confirmed deprecation date with the
qualification evidence. No live lifecycle result is recorded here.

## Replace or revoke a token

Replace an expired or revoked token through the existing connection recovery
flow. To invalidate it at Meta, revoke it in **Business Settings > Users >
System users**. Removing the Praxis connection removes the stored credential
through the shared deletion path; it does not revoke the token at Meta.

## Live qualification record

On 24 September 2026, the maintainer accepted the setup assumptions and waived
live checks for implementation. These checks were not performed. No live
credential or designated test-asset evidence is recorded.

For deployment qualification, record the date, Graph version, app mode,
permission access levels, and anonymised asset aliases for these checks:

| Check | Evidence still required |
| --- | --- |
| Partner access | Read and designated reversible write on an owned and a partner ad account; required operation on a partner Page |
| Identity and discovery | System user identity, granted permissions, and populated account tasks for owned and partner assets |
| App secret | Successful correct proof and redacted exact error bodies for missing proof and a second app's token |
| API tier | Initial tier and the dashboard's Full access request prerequisites |
| Connection UI | Owned and partner discovery, selection beside a Google Ads account, and read-only reporting access |
| Recovery and secrecy | Invalid-token and wrong-app guidance, with no token or proof in logs or audit evidence |

Keep tokens, secrets, proofs, identifying asset values, and echoed URLs out of
the record. Consult Meta's [system user overview](https://developers.facebook.com/docs/marketing-api/system-users/overview),
[request security guidance](https://developers.facebook.com/docs/graph-api/securing-requests),
[Marketing API authorisation](https://developers.facebook.com/docs/marketing-api/get-started/authorization),
and [versioning reference](https://developers.facebook.com/docs/marketing-api/overview/versioning)
when qualifying a deployment. Attempts to retrieve the first three references
on 24 September 2026 failed; the documentation lookup is not live API evidence.
