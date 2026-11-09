# Google Ads implementation

Read this when changing Google Ads connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/google_ads/)
and [frontend module](../../../apps/web/src/integrations/google_ads/index.ts).

## Account facts

Discovery stores each account's `currency_code` and `time_zone` in
`permissions_metadata`. Write tools read both through `account_facts` in
`tools/utils/accounts.py`, which asks the operator to refresh the
connection when either is missing. Approval display arguments carry the
trusted `_accounts` list: `customer_id`, `name`, `currency`, and
`time_zone` for each account the call touches. The web reads it with
`parseApprovalAccounts` and shows it with `accountContextLine`.

`google_ads_get_accounts` reads, for each selected account, its name,
status, currency, time zone, manager flag, auto-tagging, and today's and
this month's cost. Costs are exact decimal strings in the account currency.
Today is the current date in the account time zone. Manager accounts have
no cost of their own, so the tool skips the cost query and returns null
costs. Billing and spending limits are pending (plan 314).

## Backend writes

Google Ads contributes report and field discovery plus approval-only
writes for recommendations, negative keywords, positive-keyword creation and
mutable-field updates, and permanent removal,
responsive search ad creation, status changes, device bid adjustments, campaign-budget creation,
amount updates, assignment, and unused-budget removal. Label creation, apply,
and remove default to approval and also support auto policy; label deletion
is approval-only. Keyword and budget
writes re-read provider state after approval and retain exact outcome evidence
through the shared mutation ledger.

Every partial-failure mutate response is reconciled per operation by
`reconcile_mutation_outcomes`. Each operation supplies the resource name it
can produce: an exact name when it is known before submission, or a
customer-scoped pattern for creates. An error attributed to an operation marks
it failed. A unique resource name that passes the check marks it applied. Every
other operation is unverified, including when results cannot be aligned with
the submitted operations, when Google reports an error it does not attribute,
and when one operation has both an error and a result. A malformed result row
prevents applied outcomes for its siblings but never hides that contradiction.
Unverified outcomes are
recorded, never raised, so the audit record keeps every operation's evidence.

### Edit and build seams

Task-shaped write tools send every change through one `googleAds:mutate`
request per account (`operations/mutate.py`), rather than one service
endpoint per resource type. Two seams build on it:

- **Edit seam** (`operations/edits.py`). A tool describes each change as a
  `FieldChange` (new values for some settings of one object, by JSON field
  path) or a `CriterionChange` (add or remove one criterion, because a
  criterion's value can't be updated). The tool supplies a read function
  that returns each object's live values. `prepare_edits` fills the
  **Before** values, then dry runs the real changes with `validateOnly`
  and partial failure. A missing object or Google's rejection comes back as
  the edit's `refused` reason, for the approval card to show as a problem.
  `apply_edits` reads again and refuses any object whose live values differ
  from **Before** as `CHANGED_SINCE_APPROVAL`. It skips edits already at
  their values as `already_set` without sending them, sends the rest in one
  partial-failure request, and reads each object back. The read-back settles
  an unclear reply and fails a change Google accepted but didn't keep. If
  the read-back fails, Google's reply stands and **After** is empty.
- Partial-failure parsing (`grouped_partial_failure_errors`) replaces
  Google's generic policy message with the policy topics from the error's
  `policyFindingDetails`, such as "Disapproved under the Destination Not
  Working policy."
- **Build seam** (`operations/build.py`). `CampaignBuild` collects the
  objects to create in one account. Budgets, assets, campaigns, ad groups,
  and asset groups get temporary resource names (`-1`, `-2`, and so on).
  A step that refers to a temporary name the build hasn't made is
  rejected. Steps are sent parents first: budgets, assets, campaigns,
  campaign criteria, ad groups, keywords, ads, asset groups, then links.
  `dry_run_build` reports each step Google rejects. `send_build` sends one
  atomic request (`partialFailure: false`), so a rejection creates nothing,
  and maps each temporary name to its real resource name.

Both seams return the shared mutation ledger, so `terminal_operation_detail`
records them like any other write. A request Google never received or
rejected outright is failed; any other request error, or a cancellation,
leaves the sent changes unverified.

### Status changes

`google_ads_update_status` turns campaigns, ad groups, ads, positive
keywords, and asset groups on (`ENABLED`) or off (`PAUSED`): up to 100
objects per call across kinds and accounts, in one approval. Each entry in
`changes` is tagged by `kind`, carries that kind's scoped reference, and
sets its own status, so one call can turn some objects off and others on.
Ads use `google_ads_ad` references (`adGroupAds/{ad_group_id}~{ad_id}`) and
asset groups use `google_ads_asset_group` references; both have entity
resolvers. Ad lookup searches by ad group name, because most responsive
search ads have no name, and labels an unnamed ad with its first headline.
Every entity list operation (`operations/list_*.py` for campaigns, ad
groups, ads, keywords, asset groups, budgets, labels, and shared sets) takes
`exclude_removed`, on by default. It leaves out removed objects and anything
under a removed ad group or campaign, because Google refuses changes to them.
No tool turns it off today. The status tool reads removed objects through its
own query.

While preparing the approval, the tool reads each object's live status with
its campaign's, and its ad group's for ads and keywords
(`operations/read_status.py`, one query per kind, run in turn because
concurrent requests would share the caller's database session), then dry runs the real changes through the
edit seam. The trusted `_checks` display argument, keyed by resource name,
carries each object's live status, its parents' names and statuses, the
status the check was made for, and any problem: Google's dry-run rejection,
prefixed "Google says:", an object that no longer exists, or a removed object. An account that can't
be read marks its objects `unavailable`. The card can change each status and
cancel changes, but the tool refuses any object the agent didn't propose.

After approval, each edit's **Before** is the status the card showed, so the
edit seam refuses an object whose status changed since
(`CHANGED_SINCE_APPROVAL`). Objects without a check, missing objects, and
removed objects are refused without a request. Objects already at the
requested status are reported as `already_set`. The rest go in one
partial-failure `googleAds:mutate` request per account with a `status` mask,
and each result row records **Before**, **Requested**, and the status read
back as **After**.

### Ad creation

`google_ads_create_ads` creates up to 50 responsive search ads in existing
Search ad groups of one account, in one approval. Each ad in `ads` has 3 to
15 headlines (30 characters), 2 to 4 descriptions (90 characters), each
with an optional pin, a final URL, an optional mobile final URL, optional
`path1` and `path2` (15 characters; `path2` needs `path1`), and 1 to 10
ad group references. Headlines and descriptions must each be different. One
request names at most 100 ad groups. `status` is `PAUSED` unless the
operator chooses Launch (`ENABLED`).

The ad model (`GoogleAdsResponsiveSearchAd` in `tools/schemas/ads.py`) has
no ad groups of its own, so ad group and campaign creation can nest it.
`operations/responsive_search_ads.py` compiles one `AdGroupAd` per ad and
ad group pair (`ad_group_ad_body`) and reads created ads back with their
policy review (`read_ad_reviews`).

While preparing the approval, the tool reads the ad groups. An ad group that
isn't found (missing, removed, or in a removed campaign), or one outside a
Search campaign, is a problem on the card and is left out of the dry run. The
rest go through the build seam's dry run. The trusted `_checks` display argument holds each ad group's
name, campaign, and problem; for each proposed ad, the copy that was checked
and Google's rejections with the ad group each one names; and whole-request
problems. An account that can't be read is `unavailable`.

After approval, every pair goes in one atomic request through
`send_build`, so Google creates every ad or none. Each created ad is read
back for its status and review state; a failed read leaves those empty and
the ad still counts as created. Audit intents are keyed by build step. The
card can change copy, links, status, and ad groups, and cancel ads; ad
groups it adds come from the entity resolver, and the dispatcher still
holds every reference to the active context.

Reports declare the configured structured-result budget for transcript output
and preview only account row lists on overflow. Shared retrieval guidance
directs full-report calculations to the retained File through `read_table`
inside `run_code`.
Reports consume all `searchStream` batches without adding a GAQL `LIMIT` or
discarding rows. An explicit query `LIMIT` remains unchanged; the tool description
reserves it for requested limited or top-N reports. Large successful results
retain every row in
the saved File, with only the model and transcript preview shortened. The agent
uses `read_file` or `read_table` to inspect that File instead of repeating the query.
All selected accounts share the smaller of the agent-file and JSON-file byte
limits. Each response stream uses the remaining allowance, and account metadata
counts towards the complete result. Overflow stops further accounts and fails
the report without returning partial data. The normal HTTP and tool timeouts
still apply. See the
[retained-result contract](../tool-dispatch.md#retained-results-and-artifacts).

The report-field discovery tools run one audited operation against the first
selected account and are designed so one call answers one question.
`google_ads_list_report_fields` follows every field-search page and retains all
matching fields, metrics, segments, and attribute resources by default. An explicit
`limit` selects a subset of fields, metrics, and segments. The catalogue uses the
same combined File byte limit as reports. Field discovery uses the shared
saved-result preview and loads into its existing tool card.
The list tool
matches each space-separated search term locally, so `shared_set keyword`
finds both `shared_criterion.shared_set` and `shared_criterion.keyword.text`.
When no term matches, the tool returns the whole catalogue with
`search_matched` false instead of an empty result that invites guessing.
`google_ads_get_report_field` accepts up to ten names per call and lists the
ones Google Ads does not know in `missing`, so the model never probes fields one
at a time. An unknown resource name for the list tool still maps the Google Ads
404 to a `ModelRetry` naming the missing value.

### Keyword targets and evidence

Positive-keyword creation and updates
accept only Search-standard and Display-standard targets. CPC bids require
manual CPC and, for Display, a keyword custom-bid dimension. Display placement
targeting may instead use a keyword bid modifier. CPM, CPV, and percent-CPC
bids are not keyword fields. Before provider execution, keyword updates reserve
per-account shares of the complete transcript budget, including all account
envelopes and maximally escaped diagnostics. Live preparation must fit the
reserved share and the terminal audit bound. Public results retain all accepted
rows; only model results sample. Keyword removal accepts up to 500 selected
criteria, rejects changed criterion state during reference hydration and
post-approval verification, and retains each prior configuration with its
requested removal and independent outcome. Removed criteria cannot be
re-enabled. Keyword suffixes, custom parameters, and mobile
destinations support inherited ad destinations. Changing a keyword tracking
template or final URL preserves Google's template-to-final-URL dependency;
unrelated status changes leave inherited settings intact. URL
custom-parameter names use ASCII letters and numbers, are unique ignoring
case, and use Google Ads' UTF-8 byte limits. Budget
removal fails before mutation when any selected budget has a live campaign
reference.

### Labels

`google_ads_create_labels` creates 1 to 50 text labels in each selected
account. It defaults to approval, and operators can switch it to auto. It
pins the v24 bounds: names of 1 to 80 characters, descriptions of up to 200
characters, and `#RGB` or `#RRGGBB` background colours. Names must be unique
within a request, ignoring case. The operation reads the account's enabled
labels first and reports a name that already exists, ignoring case, as
`already_exists` without a write. An existing label's row shows the name,
description, and colour Google Ads holds, while the audit intent keeps the
requested values. Created labels return reusable `google_ads_label`
references carrying the created name, description, colour, and status.
Results that Google Ads doesn't account for are `unverified`, not failed.
When any label is unverified, the account result is `unverified_mutation`
and still carries every label row, which the presenter shows.

Label lookups return only labels whose resource belongs to the selected
customer, so manager-owned labels never become targets. Hydrated label
references carry the name, description, colour, status, and live association
counts for campaigns, ad groups, positive keywords, other ad group criteria
such as negative keywords, and ads. Each entity type
reads up to 10,001 association rows as a sentinel and reports at most 10,000;
more than 10,000 marks the counts as lower bounds. `verify_labels` re-reads
label IDs and fails when a label is missing or removed. The label resolver
registers with the apply, remove, and delete tools.

`google_ads_apply_labels` attaches 1 to 10 label references to 1 to 500
targets, and `google_ads_remove_labels` detaches them. Each target is an
explicit union tagged by `kind`: `campaign`, `ad_group`, or `keyword`, carrying
the matching scoped reference. Keywords are positive keywords only. The `ad`
kind is pending (plan 312). The tools never accept raw resource
names; the operation rebuilds each `campaignLabels`, `adGroupLabels`, or
`adGroupCriterionLabels` resource name from the IDs.

Labels apply only within their own account. Each account must have both labels
and targets, so a label from one account never pairs with a target from
another. Each call covers at most 500 label and target pairs across accounts.
After approval, the tool re-reads the labels and targets and fails before any
write when one is missing, removed, or changed. The operation reads the
existing associations first: apply reports an existing pair as
`already_applied`, and remove reports an absent pair as `not_applied`, without
a write. It then sends one partial-failure mutate per entity service. When a
later service request fails after an earlier one applied, the tool records that
service's pairs as failed or unverified instead of raising. Remove never
changes the label itself. The audit record groups intents by label, with one
item per target.

`google_ads_delete_labels` permanently deletes 1 to 50 label references, and
Google Ads detaches each deleted label from every item. It is approval-only and
doesn't support auto policy. The approval hydrates each label through the
resolver and shows its live association counts by entity type. After approval,
`verify_labels_with_associations` re-reads the labels and their counts and
fails before any write when a label is missing or removed. The tool sends one
partial-failure `labels:mutate` remove request per account. Each result row
and audit intent records the re-read counts, which for a deleted label are the
associations Google Ads removed with it.

## Frontend modules

Google Ads non-visual presenter helpers live in `google_ads/lib`. Entity
types and parsers belong to their domain modules: `campaign-budgets.ts`,
`campaigns.ts`, `ad-groups.ts`, `positive-keywords.ts`, `negative-keywords.ts`,
and `recommendations.ts`. Account facts and the account overview parser belong to `accounts.ts`.
Import directly from those modules. Shared scalar and URL-field validation
lives in `field-values.ts`; callers own normalisation, defaults, and clears.
Label draft parsing, approval validation, and the label-reference guard
belong to `labels.ts`. Draft validation counts code points and approximates
the server's case folding without the browser locale; the server remains
authoritative. `GoogleAdsLabelChip` always shows the label name beside a decorative colour
swatch. `labels.ts` also parses label and target arguments for apply and remove,
rejecting unknown target kinds and repeated targets. Their approval shows the
labels and the targets grouped by type, and the result shows one outcome row
per label and target pair, ordered by type. Label deletion uses a destructive
approval card with each label's association counts as text; truncated counts
read as "at least", and missing counts are stated rather than shown as zero.
Scoped negative-keyword evidence belongs to `scoped-negative-keyword-results.ts`.
It reconciles operation-specific exact rows, per-target counts, aggregate
counts, and truncated samples while retaining historical count-only results.
Account metadata requires a nonblank label and a valid currency code.

New Google cards build from the shared ads card kit in
`integrations/ads/components/`, which Meta also uses: `SettingRows`,
`SettingRow`, `SettingLine`, `StatusChoice`, `ChangeBanner`, `ChangeSummary`,
`AttentionLine`, `MoneyField`,
`EntityPicker`, and the form controls (`ChoiceCards`, `SegmentedChoice`,
`Chip`, and the labelled fields). The kit depends on no provider package,
and dependency rules enforce that. `StatusChoice` is one plain line: Status, the
choice, and a note such as "Paused. Will not appear or spend until
activated." or "Active, pending approval. Will go live once approved by
Google." Campaign and ad group notes leave out approval. The older Google kit
(`GoogleAdsApprovalSection`, `GoogleAdsEntityCard`, `GoogleAdsBeforeAfter`,
`GoogleAdsOutcomeTable`) stays only for the tools plans 307, 308, and 312
replace.

### Outcome evidence

Outcome vocabulary, token labels, lifecycle copy, and result envelopes have
separate modules. Device bid modifiers, campaign list links, budget amount
updates, budget assignments, budget removals, recommendations, list/campaign/
ad-group negative keywords, and positive-keyword creation, update, and removal
share `GoogleAdsOutcomeTable` and `GoogleAdsFailureTargets`. The table owns
outcome labels, stat order and tones, conditional detail and error columns,
and sample notices. Tool columns and result validation stay with each tool. Legacy negative-keyword aggregates
retain counts without reconstructing keyword identities. Keyword update results
separate Before, Requested, and verified After values. Budget assignment and
amount results use the same distinction, with Unconfirmed after values for failed
or unverified outcomes. Budget amount deltas and monthly estimates describe
requested values. Budget and keyword-creation sample envelopes and list negative
keyword results use shared per-outcome count validation, including truncated
sample upper bounds. List errors retain account-level failure semantics. Negative keyword list
creation also uses the shared outcome table, with Name as its leading column.
Budget creation retains its single card and uses the shared outcome label.

### Approval composition

Approval summaries use `GoogleAdsApprovalSection` and `GoogleAdsEntityCard`.
Ad-group targets use `GoogleAdsEntityGroup`; approval scale uses one count
line instead of result stats. Budget amount changes, budget assignments, and
keyword status use `GoogleAdsBeforeAfter`, whose proposed slot accepts the
existing status editor. Budget removal uses the destructive section. Keyword
removal retains its consequence warning in a neutral section.
Every write variant uses `googleAdsWriteCopy`; keep semantic overrides visible
in the presenter, including declined recommendation dismissal. Campaign and
ad-group negative keywords each declare their add and remove variants directly.
Presenters compose `google_ads/components` and `google_ads/lib`: a new tool
adds no outcome table, approval section, or lifecycle template. Architecture
checks forbid direct Stat and Badge imports, and only the two report
presenters import the generic DataTable. The accounts card reaches DataTable
through `components/accounts-table.tsx`: one table across all accounts, with
money in each row's own currency. Bid adjustment formatting belongs
to `lib/bid-modifiers.ts`. Tool-specific summaries stay inside the shared
approval section. Construct presenters using this shared kit.


### Update Status card

`google_ads_update_status` turns campaigns, ad groups, ads, keywords, and asset
groups on or off in one approval. `lib/status-change.ts` parses `changes` with
the trusted `_accounts` and `_checks` beside it, keying each object by its
resource name. `statusRows` joins each proposed change to its check and to the
edited `changes`, so a change missing from the edit is cancelled and can come
back with Undo. A row's rejection shows and blocks approval only while its
status still equals the status the server checked; changing the status clears
it. A missing or unavailable check always blocks. An item turned on is flagged
Won't Show Yet when its parent is off and not being turned on in the same
request: the campaign for ad groups and asset groups, and for ads and keywords
the ad group, then the campaign. That flag warns and never blocks. A row whose new status equals the
live status is Already On or Already Off and isn't counted in the approve label.

The card (`components/status-change-approval.tsx`) shows the banner, one
`ChangeSummary` line per kind of change, an `AttentionLine` when anything
blocks, and one change table grouped by campaign. Each summary line filters the
table, and the Turn Off and Turn On lines carry an On/Off choice that sets every
item in the line. Below ten items the summary and table tools are left out.
Edits go out as the whole `changes` value: each entry keeps its reference as
received, only `status` changes, and cancelled entries are omitted. The card
never adds entries. The approve label counts the changes that will run and
reads the edited arguments, through the write presenter's `approveLabel`
function form.

The result is one `DataTable` inside the usual result card, with Item, Kind,
Campaign, Before, After, and Outcome columns and tabs for All, Changed,
Already Set, Failed, and Unconfirmed when any. It opens on Failed when anything
failed, and the CSV holds every row. Already Set is never a failure.

### Create Ads card

`lib/create-ads.ts` parses `ads` and `status` with `_accounts` and
`_checks`. It accepts copy over the limits so the card can show the problem,
and keeps each entry and ad group reference as received so edits keep their
fields. `adRows` lists each ad's problems: counts, character limits
(counted per code point, like the server), repeated text, URLs, paths, no
ad group, an ad group's problem, and Google's dry-run rejections. Google's
rejections apply only while the ad's copy matches the checked copy
(`copyKey`), and only for ad groups still on the ad. Any problem blocks
approval. The approve label counts ads times ad groups.

The card (`components/create-ads-approval.tsx`) shows `StatusChoice`
(Paused or Active). With more than one ad it adds `ChangeSummary`
lines for a final URL and display paths that every ad shares, edited once;
Needs Attention with Cancel These N; and Cancelled with Restore. Then
`AttentionLine`, and one `DataTable` of ads with All and Needs Attention
tabs. Clicking an ad's row opens it below (Previous and Next step
through the ads), with
`SearchAdPreview` (a Google result in Google's light or dark colours,
named from the final URL's host; pinned assets in place, then the rest in
order),
`TextAssetList` for headlines and descriptions (counters, pins, the
minimum, the first three until Show All), link fields, and ad group chips
with an `EntityPicker` to add one. Cancelling takes the ad out of `ads`;
the card keeps cancelled ads until approval so Restore can put them back.

The result (`components/create-ads-outcome.tsx`) is one `DataTable` with Ad
Group, Headline 1, Status, Review, and Outcome. When nothing was created it
says so once with Google's reason, because the request is atomic.

### Data table extensions

The core `DataTable` stays generic and also serves bulk cards. It filters rows
before paging, so counts, pages, and the row total follow the view:

- `tabs` adds filter tabs with counts. Each tab has a `match` function, and
  `hideWhenEmpty` drops it while nothing matches. `activeTab` and
  `onTabChange` control the tab from outside, such as a change summary line.
- `searchable` adds a search box that matches every word across all columns,
  hidden ones included.
- `selection` adds a checkbox column, a select-all for the filtered rows, and
  a bulk bar showing the count with caller-supplied `actions`. The caller owns
  the selected ids.
- `groupBy` gathers rows under heading rows and turns column sorting off.
- `renderCell` cells may hold controls, such as a select or a cancel button.
  Pair them with `rowDetails={false}` so a click doesn't open the details
  sheet, and use `rowClassName` to dim a row.
- `onRowClick` makes the whole row a button that calls it instead of opening
  the details sheet, as Create Ads does to open an ad. Controls in a cell
  stop the click's propagation.
- CSV export and copy hold every row, not only the filtered view.

### Keyword editors

Google Ads positive-keyword creation groups approval context by campaign,
keeps optional bid and URL fields behind each row's progressive disclosure,
applies provider byte and dependency checks before approval, and shows
requested settings separately from an observed duplicate. It shows one
guarded, exportable outcome row per ad-group and keyword pair. Its update
action uses compact fixed, paginated keyword rows with shared account context
and per-row More fields disclosures. Fields are directly editable, with colour
and before/after indicators for changed values. It shows trusted currencies, supports
explicit nullable scalar clears, and keeps recoverable invalid drafts mounted
while blocking approval. Literal URL settings remain exact in comparisons and
exports; requested projections are labelled as requested state. Complete
results validate per-outcome counts and unique keyword identities before
presenting one exportable row per selected criterion. Keyword removal has a
separate approval card with a permanent-removal warning and account and ad-group context. Its
paginated result table distinguishes confirmed removal, failure, and
unverified outcomes, and rejects incomplete or contradictory result evidence.
