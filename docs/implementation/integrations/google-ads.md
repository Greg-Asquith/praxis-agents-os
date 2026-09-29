# Google Ads implementation

Read this when changing Google Ads connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/google_ads/)
and [frontend module](../../../apps/web/src/integrations/google_ads/index.ts).

## Backend writes

Google Ads contributes report and field discovery plus approval-only
writes for recommendations, negative keywords, positive-keyword creation and
mutable-field updates, and permanent removal,
campaign status, device bid adjustments, campaign-budget creation,
amount updates, assignment, and unused-budget removal. Label creation, apply,
and remove default to approval and also support auto policy. Keyword and budget
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

Reports declare the configured structured-result budget for transcript output
and preview only account row lists on overflow. Shared retrieval guidance
directs full-report calculations to the retained File through `run_code`.
Reports consume all `searchStream` batches without adding a GAQL `LIMIT` or
discarding rows. An explicit query `LIMIT` remains unchanged; the tool description
reserves it for requested limited or top-N reports. Large successful results
retain every row in
the saved File, with only the model and transcript preview shortened. The agent
uses `read_file` or `run_code` to inspect that File instead of repeating the query.
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
counts for campaigns, ad groups, positive keywords, and ads. Each entity type
reads up to 10,001 association rows as a sentinel and reports at most 10,000;
more than 10,000 marks the counts as lower bounds. `verify_labels` re-reads
label IDs and fails when a label is missing or removed. The label resolver
registers with the apply and remove tools.

`google_ads_apply_labels` attaches 1 to 10 label references to 1 to 500
targets, and `google_ads_remove_labels` detaches them. Each target is an
explicit union tagged by `kind`: `campaign`, `ad_group`, or `keyword`, carrying
the matching scoped reference. Keywords are positive keywords only. The `ad`
kind is pending until ad references exist. The tools never accept raw resource
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

## Frontend modules

Google Ads non-visual presenter helpers live in `google_ads/lib`. Entity
types and parsers belong to their domain modules: `campaign-budgets.ts`,
`campaigns.ts`, `ad-groups.ts`, `positive-keywords.ts`, `negative-keywords.ts`,
and `recommendations.ts`. Account-currency metadata belongs to `accounts.ts`.
Import directly from those modules. Shared scalar and URL-field validation
lives in `field-values.ts`; callers own normalisation, defaults, and clears.
Label draft parsing, approval validation, and the label-reference guard
belong to `labels.ts`. Draft validation counts code points and approximates
the server's case folding without the browser locale; the server remains
authoritative. `GoogleAdsLabelChip` always shows the label name beside a decorative colour
swatch. `labels.ts` also parses label and target arguments for apply and remove,
rejecting unknown target kinds and repeated targets. Their approval shows the
labels and the targets grouped by type, and the result shows one outcome row
per label and target pair, ordered by type.
Scoped negative-keyword evidence belongs to `scoped-negative-keyword-results.ts`.
It reconciles operation-specific exact rows, per-target counts, aggregate
counts, and truncated samples while retaining historical count-only results.
Account metadata requires a nonblank label and a valid currency code.

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
sample upper bounds. List errors retain account-level failure semantics. Campaign status and
negative keyword list creation also use the shared outcome table, with Campaign
and Name as their leading columns. Campaign failures use shared label chips.
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
presenters import the generic DataTable. Bid adjustment formatting belongs
to `lib/bid-modifiers.ts`. Tool-specific summaries stay inside the shared
approval section. Construct presenters using this shared kit.

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
