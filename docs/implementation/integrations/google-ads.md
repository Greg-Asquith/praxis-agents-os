# Google Ads implementation

Read this when changing Google Ads connections or tools. The
[shared integration contracts](README.md) also apply. Backend paths are
relative to `apps/api/`; frontend paths to `apps/web/`.

Start with the [backend package](../../../apps/api/integrations/google_ads/)
and [frontend module](../../../apps/web/src/integrations/google_ads/index.ts).

## Backend writes

Google Ads contributes bounded report and field discovery plus approval-only
writes for recommendations, negative keywords, positive-keyword creation and
mutable-field updates, and permanent removal,
campaign status, device bid adjustments, and campaign-budget creation,
amount updates, assignment, and unused-budget removal. Keyword and budget
writes re-read provider state after approval and retain exact outcome evidence
through the shared mutation ledger.

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

## Frontend modules

Google Ads non-visual presenter helpers live in `google_ads/lib`. Entity
types and parsers belong to their domain modules: `campaign-budgets.ts`,
`campaigns.ts`, `ad-groups.ts`, `positive-keywords.ts`, `negative-keywords.ts`,
and `recommendations.ts`. Account-currency metadata belongs to `accounts.ts`.
Import directly from those modules. Shared scalar and URL-field validation
lives in `field-values.ts`; callers own normalisation, defaults, and clears.
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
