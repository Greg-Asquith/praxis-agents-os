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
costs. Billing and spending limits are pending.

## Backend writes

Google Ads contributes report and field discovery plus approval-only
writes for recommendations, negative keywords, search terms, positive-keyword creation and
bid, URL, and match type changes,
Search campaign, ad group, and responsive search ad creation, status changes, campaign settings, location and language targeting, device bid adjustments, budget
changes, and permanent removal of any supported kind. Label creation, apply,
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

### Edit and build seams

Task-shaped write tools send every change through one `googleAds:mutate`
request per account (`operations/mutate.py`), rather than one service
endpoint per resource type. Two seams build on it:

- **Edit seam** (`operations/edits.py`). A tool describes each change as a
  `FieldChange` (new values for some settings of one object, by JSON field
  path), a `CriterionChange` (add or remove one criterion, because a
  criterion's value can't be updated), or a `Removal` (remove one object,
  such as a budget no campaign uses). Campaign, ad group, and shared list
  criteria are criteria here, and so is a campaign's use of a shared list
  (`campaignSharedSet`). The tool supplies a read function
  that returns each object's live values. `prepare_edits` fills the
  **Before** values, then dry runs the real changes with `validateOnly`
  and partial failure. A missing object or Google's rejection comes back as
  the edit's `refused` reason, for the approval card to show as a problem.
  `apply_edits` reads again and refuses any object whose live values differ
  from **Before** as `CHANGED_SINCE_APPROVAL`. It skips edits already at
  their values as `already_set` without sending them, sends the rest in one
  partial-failure request, and reads each object back. Edits that share an
  `atomic_group` go in their own request with `partialFailure: false`, so
  Google applies all of them or none. Google's rejection of a whole request
  doesn't name the operation that caused it, so every edit in the group
  fails with Google's message. A group happens whole or not at all, so an
  edit refused at approval or as changed since approval refuses the rest of
  its group without a request. The read-back settles
  an unclear reply and fails a change Google accepted but didn't keep. If
  the read-back fails or doesn't return the object, Google's reply stands and
  **After** is empty. A cancel during the read-back keeps Google's reply as the
  evidence. A cancel between requests keeps the replies of the requests that
  finished and leaves the rest unverified.
- Partial-failure parsing (`grouped_partial_failure_errors`) replaces
  Google's generic policy message with the policy topics from the error's
  `policyFindingDetails`, such as "Disapproved under the Destination Not
  Working policy."
- **Build seam** (`operations/build.py`). `CampaignBuild` collects the
  objects to create in one account. Budgets, assets, campaigns, ad groups,
  asset groups, and shared lists get temporary resource names (`-1`, `-2`,
  and so on).
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
keywords, and asset groups on (`ENABLED`) or off (`PAUSED`): up to 500
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

### Campaign settings

`google_ads_update_campaigns` changes up to 50 live campaigns of any type in
one approval. Each entry names one campaign and only the settings that change.
Conversion goals and Performance Max and Shopping settings are pending. The
fields are as follows:

| Field | What it does |
| --- | --- |
| `name` | Renames the campaign. Line breaks and repeated spaces become one space. |
| `start_date` | Sets the start date (`YYYY-MM-DD`, account time zone). Sent as `startDateTime` at `00:00:00`. |
| `end_date` | Sets the end date, sent as `endDateTime` at `23:59:59`, or `"none"` to run with no end date. |
| `url_options` | `final_url_suffix`, `tracking_template`, and `custom_parameters` (up to 8 pairs, replacing the list). An empty value or list clears it. |
| `networks` | `search_partners` (Search and Shopping) and `display_expansion` (Search) on or off. |
| `bidding` | One of `MANUAL_CPC`; `MAXIMIZE_CLICKS` with an optional `max_cpc`; `MAXIMIZE_CONVERSIONS` with an optional `target_cpa`; `MAXIMIZE_CONVERSION_VALUE` with an optional `target_roas` ratio; `TARGET_IMPRESSION_SHARE` with `location`, `share_percent`, and `max_cpc`; `PORTFOLIO` with a `google_ads_bidding_strategy` reference from the campaign's account; or `TARGETS` with `target_cpa`, `target_roas`, or `max_cpc`, changing only targets on the current strategy. Leaving out an optional target removes it. |

`operations/campaign_settings.py` reads each campaign's settings by ID,
including removed campaigns, and holds two forms of each value: Google's, by
JSON field path, which the edit seam compares and masks, and the card's, with
dates as `YYYY-MM-DD` and no end date as null. A `FieldChange` path whose
requested value is null stays in the update mask and out of the body, which
is how Google clears a field, such as the end date.

#### Bidding

`operations/campaign_bidding.py` holds bidding in card terms (`card_bidding`:
the strategy and only its own fields, money as a canonical decimal string),
and works out what a change sends (`bidding_paths`). Google's bidding is one
oneof on the campaign, and it refuses an update mask naming a strategy field
that has subfields set. So staying on a strategy names each field inside it,
and the edit seam sends only the targets that differ. Moving to another
strategy names the fields it sets, or the bare strategy field when it sets
none (`manualCpc`, or Maximise Conversions with no target). A portfolio is the
`biddingStrategy` field. Setting any member moves the campaign off the
others, portfolio included.

A `TARGETS` request resolves against the live strategy
(`resolved_bidding`): a target CPA needs Maximise Conversions (or the older
standard Target CPA), a target ROAS needs Maximise Conversion Value (or Target
ROAS), and a maximum click bid needs Maximise Clicks or Target Impression
Share. A campaign on a portfolio strategy changes targets on the strategy,
not here. Strategies are offered per channel as in Google's v24 strategy
types table (`strategy_problem`), and a portfolio must exist in the
campaign's account (`operations/list_bidding_strategies.py`, which lists
account-owned portfolios only).

A bidding edit sets `FieldChange.compared` to `biddingStrategyType` and
`biddingStrategy`. The seam compares those read-only paths with the approved
values but never sends them, so a strategy someone changed since approval is
refused (`CHANGED_SINCE_APPROVAL`) rather than replaced.

For a strategy change, the check reads the campaign's live ad groups
(`read_ad_group_bids`) and, when the new strategy uses conversions, its
conversions over the last 30 days (`read_conversions`). Its `notes.bidding`
says how many conversions there were, which ad groups have their own target
CPA or ROAS, and which CPC bids stop being used (moving off Manual CPC) or
start to matter (moving onto it). `learning` marks a strategy change, which
restarts Google's learning; a target change doesn't.

#### Checks

While preparing the approval, the tool reads each campaign, checks Google's
rules locally, and dry runs the rest through the edit seam:

- A campaign that has started can't change its start date, because Google
  refuses it (`CANNOT_MODIFY_START_DATE_IF_ALREADY_STARTED`). Started means its
  start date is on or before today in the account time zone.
- A new start date must be after today, and a new end date today or later.
- The end date can't be before the start date, after the request's dates are
  applied to the live ones.
- A network the channel doesn't support is refused before Google sees it.
- A target the current strategy doesn't take, a strategy the channel doesn't
  offer, or a missing portfolio is refused before Google sees it.

The trusted `_checks` display argument, keyed by campaign resource name, holds
the campaign's name, status, and channel, its `current` settings in card terms,
the `requested` settings the check covered, Google's `values` for those
settings and bidding guards (what approval plans against), the bidding
`notes`, `learning`, and the `portfolios` named (name and type by resource
name), a campaign `problem` (missing, removed, or Google's dry-run rejection
prefixed "Google says:"), and `problems` by setting. Edits on the card need a new check (`approval_review_fields`).
After approval, a campaign whose request differs from its check, or whose check
showed a problem, is refused without a request. The rest go in one
partial-failure `googleAds:mutate` request per account, masking only the
settings that differ from the live values. Each result row is one setting with
**Before** (as the card showed it), **Requested**, **After** (read back), and
its outcome; a setting already at its value is `already_set`. Bidding values in
the result are card terms; the result also carries the account `currency` and
the `portfolios` named, so the card can write them out.

### Ad group settings

`google_ads_update_ad_groups` changes up to 50 live ad groups in one approval.
Each entry names one ad group with a `google_ads_ad_group` reference and only
the settings that change. The fields are as follows:

| Field | What it does |
| --- | --- |
| `name` | Renames the ad group. Line breaks and repeated spaces become one space. |
| `cpc_bid` | Sets the default click bid (`cpcBidMicros`). It can't be removed, because Google always keeps one. |
| `target_cpa` | Overrides the campaign's target CPA (`targetCpaMicros`), or `"none"` to remove the override. |
| `target_roas` | Overrides the campaign's target ROAS as a ratio (`targetRoas`), or `"none"` to remove the override. |
| `url_options` | `final_url_suffix`, `tracking_template`, and `custom_parameters`, as for campaigns. |
| `ad_rotation` | `OPTIMIZE` or `ROTATE_FOREVER` (`adRotationMode`). |

`operations/ad_group_settings.py` reads each ad group by ID with its
campaign's name, status, and bidding (`read_ad_group_settings`), and holds
Google's and the card's form of each value, as campaign settings do. Every
field is a scalar, so a mask names it directly, and a removed target is masked
with no value. `ad_group_bids_used` in `operations/campaign_bidding.py` says
which ad group bid fields the campaign's bidding uses: a CPC bid only under
manual bidding with no portfolio; a target CPA under Target CPA, or Maximise
Conversions with a campaign target CPA or a portfolio; a target ROAS under
Target ROAS, or Maximise Conversion Value with a campaign target ROAS and no
portfolio. Create Ad Groups and Create Campaign use the same rule.

While preparing the approval, a bid or target the strategy doesn't use is a
problem that names the campaign and its strategy, such as "Waterproof Range
uses Maximise Conversions, so Google doesn't use an ad group CPC bid." A
target under Maximise Conversions or Maximise Conversion Value with no
campaign target asks for one on the campaign first. Removing a target is
always allowed. The rest are dry run through the edit seam. `_checks`, keyed by
ad group resource name, holds the ad group's and campaign's names, the
campaign's `strategy_name` and `bids_used`, `current`, `requested`, `values`,
`problem`, and `problems` by setting. An edit that changes a bid or target
sets `FieldChange.compared` to the campaign's `biddingStrategyType` and
`biddingStrategy` (read as `campaign.biddingStrategyType` and
`campaign.biddingStrategy`), so a bid whose campaign changed strategy since
approval is refused (`CHANGED_SINCE_APPROVAL`). Approval, refusal, and the
result follow Update Campaigns; the result carries the account `currency`.

### Budgets

`google_ads_update_budgets` makes up to 100 budget changes in one approval.
Each entry names either a campaign (`google_ads_campaign`) or a budget
(`google_ads_campaign_budget`, usually a shared one) and only what changes:

| Field | What it does |
| --- | --- |
| `amount` | Sets the daily amount (`amountMicros`) of the budget the campaign uses, or of the named budget. |
| `delivery` | `STANDARD` or `ACCELERATED` (`deliveryMethod`). |
| `use_shared_budget` | For a campaign: moves it onto a shared budget from the same account (`campaign.campaignBudget`). It can't be combined with `amount` or `delivery`. |

`operations/budget_settings.py` reads the named campaigns and the budgets
they use (`read_campaigns`, `read_budgets`), then every campaign on those
budgets and its cost this month (`read_budget_campaigns`). Cost is a second
query with `segments.date DURING THIS_MONTH`, because a campaign with no cost
has no metrics row. Google reports the month in the account time zone.

While preparing the approval, the tool works out the budget each change acts
on. A missing or removed campaign or budget, a total (`CUSTOM_PERIOD`) budget,
a move onto a budget that isn't shared, and a move of a draft or experiment
campaign are problems. Two changes to one budget are a problem on the later
campaign change. Moving a campaign off a budget nothing else uses also
removes that budget: the move and the `Removal` share an `atomic_group`, so
Google makes both or neither. The removal isn't dry run, because it depends
on the move. The rest are dry run through the edit seam. `_checks`, keyed by
the campaign or budget resource name, holds the name, the budget and the
destination (each with its campaigns, up to 50 named, and this month's
spend), `removes_budget`, `spend_this_month`, `days_left` in the month
counting today, `current`, `requested`, `values` by edit, and `problem`.
Spend comes only from these reads, never from the agent's arguments.

After approval, the edits are sorted so decreases go before increases, as
Meta's budget tool does. Each edit is one audit intent. The result has one
row per change with a setting outcome for each of `amount`, `delivery`, and
`shared_budget`; a shared budget is shown by name.

### Removal

`google_ads_remove_objects` is the one destructive tool. It removes up to 500
items in one approval, across kinds and accounts. Each entry names its `kind`
and the matching reference:

| Kind | Reference | Mutate resource |
| --- | --- | --- |
| `campaign` | `google_ads_campaign` | `campaign` |
| `ad_group` | `google_ads_ad_group` | `adGroup` |
| `ad` | `google_ads_ad` | `adGroupAd` |
| `keyword` | `google_ads_keyword` (positive keywords only) | `adGroupCriterion` |
| `asset_group` | `google_ads_asset_group` | `assetGroup` |
| `budget` | `google_ads_campaign_budget` | `campaignBudget` |
| `label` | `google_ads_label` | `label` |
| `bidding_strategy` | `google_ads_bidding_strategy` (portfolio) | `biddingStrategy` |
| `negative_keyword_list` | `google_ads_shared_set` | `sharedSet` |

`operations/read_removals.py` reads each kind in one GAQL read per account,
removed objects included, through `read_statuses` for campaigns, ad groups,
ads, keywords, and asset groups. For the approval it also counts what each
removal takes with it: the live ad groups, ads, and positive keywords under a
campaign or ad group; the items a label is on (`count_label_associations`);
a list's negative keywords (`shared_set.member_count`) and the campaigns it is
applied to; and the campaigns still using a budget or portfolio strategy, up
to three named. Each dependant query reads up to 10,001 rows; more than 10,000
marks the counts as lower bounds.

A missing item, and a budget or bid strategy that a non-removed campaign still
uses, are problems on the card. The rest are dry run through the edit seam as
`Removal` edits. An item already removed is shown as such and skipped. `_checks`,
keyed by resource name, holds the name, `status`, `campaign_name`,
`ad_group_name`, `dependants` (`campaigns`, `ad_groups`, `ads`, `keywords`,
`truncated`), and `problem`. The card can only cancel items: the tool refuses
an item that wasn't in the proposal.

After approval, each account's removals go in one partial-failure request,
children before parents (keywords, ads, ad groups, asset groups, campaigns,
then budgets, strategies, lists, and labels), so removing an ad group never
fails a keyword in it. A removed object reads back with a `REMOVED` status or
not at all, and both count as removed. Each result row has the kind, name,
campaign, the dependants the card showed, and `removed`, `already_removed`,
`failed`, or `unverified`. Audit intents are grouped by entity kind, one per
item, with what the removal takes with it.

Removing a campaign leaves its own budget in place; remove the budget in a
later call. Assets, bid adjustments, and other kinds are pending: their plans
add them here instead of shipping their own removal tool.

### Ad edits

`google_ads_update_ads` edits up to 50 live responsive search ads in one
approval. Each entry names one ad with a `google_ads_ad` reference and only
the edits to make:

| Field | What it does |
| --- | --- |
| `add_headlines`, `add_descriptions` | Adds text (30 or 90 characters) with an optional pin. |
| `remove_headlines`, `remove_descriptions` | Removes the headline or description with this exact text. |
| `pins` | Pins the headline or description with this text, or unpins it with a null pin. |
| `path1`, `path2` | Sets the display path (15 characters). An empty value clears it. |
| `final_url` | Replaces the ad's final URL. |

`operations/responsive_search_ad_edits.py` reads each ad by its `adGroupAds`
resource name (`read_responsive_search_ads`), including removed ads, with its
ad group and campaign names. It holds the copy in two forms: Google's, by
JSON field path (`responsiveSearchAd.headlines`, `responsiveSearchAd.path1`,
`finalUrls`), which the edit seam compares and masks, and the card's, with
headlines and descriptions as text and pin, no path as null, and one final
URL. `merged_copy` applies an entry to the live copy. An added headline or
description takes the place of a removed one, in order, so a swap keeps its
position; the rest go at the end. A pin applies to the asset with that text.

The edit is one `FieldChange` on the `ad` resource, named
`customers/{id}/ads/{ad_id}`, so it goes through `AdService` in the shared
`googleAds:mutate` request. Headlines and descriptions are always compared,
and sent whole when they change. Repeated fields are leaves in a field mask,
so `responsiveSearchAd.headlines` is a valid path. Paths and the final URL
are compared and sent only when the entry names them, and a cleared path is
masked with no value.

While preparing the approval, the tool reads the ads and refuses, before the
dry run, an ad that is missing, removed (or under a removed ad group or
campaign), or not a responsive search ad, and a merge that removes text the ad
doesn't have, repeats a headline or description, pins missing text, sets path
2 without path 1, or leaves fewer than 3 or more than 15 headlines or fewer
than 2 or more than 4 descriptions. The rest go through the edit seam's dry
run. The trusted `_checks` display argument, keyed by `adGroupAds` resource
name, holds the ad's name (its first headline when it has no name), ad group
and campaign names, status, `current` copy, the `requested` edits the check
covered, the merged `after` copy, Google's `values` for the paths it sends, a
`problem` (missing, removed, not a responsive search ad, or Google's dry-run
rejection prefixed "Google says:"), and the merge `problems`. Edits on the card
need a new check (`approval_review_fields`), and after approval an ad whose
edits differ from its check, or whose check showed a problem, is refused
without a request. Each result row is one ad with **Before**, **Requested**
(the merge), **After** (read back), the outcome, and Google's policy review
(`read_ad_reviews`), which a changed ad starts again. Whether Google accepts
an in-place update of an enabled ad is check 22 of the live QA; if it
doesn't, the edit becomes a replacement ad with the old one paused.

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

The tool declares `ads` in `approval_review_fields`, so an edited request needs
a new check. Check Changes on the card sends it to `review-approval`, which runs
these checks again on the edited request and retains the result. Approval refuses
`ads` that differ from what was checked with `approval_review_required`. Status
isn't part of the check, because it doesn't change Google's answer. See [retained
approval reviews](../tool-dispatch.md#retained-approval-reviews).

After approval, every pair goes in one atomic request through
`send_build`, so Google creates every ad or none. Each created ad is read
back for its status and review state; a failed read leaves those empty and
the ad still counts as created. Audit intents are keyed by build step. The
card can change copy, links, status, and ad groups, and cancel ads; ad
groups it adds come from the entity resolver, and the dispatcher still
holds every reference to the active context.

### Ad group creation

`google_ads_create_ad_groups` creates 1 to 20 ad groups in one live Search
campaign, in one approval. Each ad group has a name, optional keywords (text,
match type, optional click bid and final URL), negative keywords, up to 3 ads
using the ad model above, and optional bid settings. `status` is `PAUSED`
unless the operator chooses Active. It applies to the ad groups and ads;
keywords start enabled. One request creates at most 2,500 objects, because one
audit event holds 2,500 records.

Bid settings follow Google's rules, and the tool refuses any Google would
ignore or reject:

| Setting | Accepted when the campaign uses |
| --- | --- |
| `cpc_bid` and keyword `cpc_bid` | Manual CPC, not a portfolio strategy |
| `target_cpa` | Target CPA, or Maximise Conversions with a target CPA. The target of a portfolio strategy isn't read, so Google decides. |
| `target_roas` (a ratio, so 3.5 means 350%) | Target ROAS, or Maximise Conversion Value with a target ROAS, not a portfolio strategy |

`operations/search_ad_groups.py` compiles an ad group with its contents for the
build seam (`add_search_ad_group`) and reads the campaign's channel, bidding, and
up to 2,000 live ad group names (`read_search_campaign`). Each step records its
`source` (`AdGroupItem`), so a dry-run rejection names its item.

While preparing the approval, the tool reads the campaign and dry runs the ad
groups that have no bid or name problem. The trusted `_checks` display argument
holds the campaign (its bidding and what it accepts, or its problem), the live
names, and Google's rejections, each naming its ad group and item. A campaign
that is removed or outside Search is left out of the dry run. The tool declares
`campaign` and `ad_groups` in `approval_review_fields`, so an edit to either needs
a new check, as in ad creation.

After approval, the tool reads the campaign again, because accounts can change
between the check and the send. A problem stops the tool with nothing sent. The
rest goes in one atomic request, so Google creates everything or nothing. The
result counts each kind of object and returns a reference for each ad group,
for other tools to use. When Google refuses the request, the result gives each
distinct reason once. Audit intents are grouped by ad group and keyed by build
step.

### Campaign creation

`google_ads_create_campaign` builds a complete Search campaign in one approval: a budget,
the campaign, its locations and negative keywords, and 1 to 20 ad groups using the ad group
model above. It builds in the one Google Ads account with permission to make changes in
Active Context, as Meta's create tools do, because integration tools never take an account
argument. Approval pins that account: after approval, the trusted `_accounts` must still
name it, or the tool stops with nothing sent. `status` is `PAUSED` unless the operator
chooses Active, and covers the campaign, ad groups, and ads.

The `campaign` argument holds the settings, as follows:

| Field | What it does |
| --- | --- |
| `budget` | `{kind: "new", daily_amount}` creates a daily budget with standard delivery, named after the campaign. `{kind: "shared", budget}` uses an existing shared budget from the same account. |
| `bidding` | One of `MANUAL_CPC`; `MAXIMIZE_CLICKS` with an optional `max_cpc`; `MAXIMIZE_CONVERSIONS` with an optional `target_cpa`; `MAXIMIZE_CONVERSION_VALUE` with an optional `target_roas` ratio; or `TARGET_IMPRESSION_SHARE` with `location`, `share_percent`, and the `max_cpc` Google requires. Maximise Clicks is Google's `targetSpend`. |
| `search_partners`, `display_expansion` | Off by default. Google Search is always on. |
| `locations`, `excluded_locations` | Location keys from `google_ads_search_targeting`, up to 1,000 of each. At least one location is required, so the ads can't show everywhere. |
| `location_setting` | `PRESENCE` (the default) or `PRESENCE_OR_INTEREST`. |
| `start_date`, `end_date` | Dates in the account time zone. A start on or before today, or none, starts the campaign when it's turned on, because Google refuses a start time in the past. The end is the end of that day. |
| `negative_keywords` | Campaign negative keywords, up to 1,000. |
| `contains_eu_political_advertising` | Google's required declaration; false unless the operator says the ads are political and aimed at the EU. |

Languages aren't part of a Search campaign, because Google matches each ad's language.

The tool refuses, before approval and again after it, a campaign with no location, an
ad group with no keyword or no ad, and ad group bids the new bidding doesn't use. The bid
rules are those in the table above, applied to the new campaign's own bidding
(`new_campaign_facts` in `operations/search_campaigns.py`): click bids only under Manual
CPC, and a target CPA or ROAS override only when the campaign sets that target. After
approval it also refuses a start or end date before today in the account time zone, and a
shared budget from another account. One request creates at most 2,500 objects, counting
the budget, campaign, and criteria.

`operations/search_campaigns.py` compiles the budget, campaign, and campaign criteria
(`add_search_campaign`), and each ad group goes through `add_search_ad_group` with the
campaign's temporary name. Each step records its `source` (`CampaignItem` or
`AdGroupItem`), so a rejection names its item.

While preparing the approval, the tool reads Google's names for every location key, then
dry runs the build. Unknown locations, and ad groups with a problem the card already shows,
are left out of the dry run. The trusted `_checks` display argument holds the date in the
account time zone, Google's location names, the unknown keys, Google's rejections of the
campaign's own items (by kind, with the location key or negative keyword), its rejections
of ad group items (as in ad group creation), and whole-request problems. The tool declares
`campaign` and `ad_groups` in `approval_review_fields`, so an edit to either needs a new
check; `campaign` leads the review with the `google_ads_location` entity kind.

After approval, one atomic request creates everything or nothing. The result counts each
kind of object and returns references for the campaign (with its budget) and each ad
group, for other tools to use. When Google refuses the request, the result gives each
distinct reason once. Audit intents are grouped by the campaign and each ad group, keyed by
build step, and record locations by key. Sitelinks and callouts on create are pending.

### Targeting

`google_ads_search_targeting` finds locations and languages by name and returns
the keys `google_ads_update_targeting` takes. It takes up to 25 names per call,
which is Google's limit for `geoTargetConstants:suggest`, and one selected account
runs it, because the keys are the same for every account. A location option has its
key, name, type, region, and Google's estimated reach. Audit records the kind and
count, never the search text. Audience search is pending.

`google_ads_update_targeting` changes up to 20 campaigns per call in one approval.
Each entry names one campaign and only what changes. Ad group entries are pending,
because no setting in this tool applies to an ad group yet. Devices, schedules,
audiences, and exclusions are also pending. The fields are as follows:

| Field | What it does |
| --- | --- |
| `add_locations` | Targets a location, with an optional `bid_adjustment` percent from -90 to 900. Naming a location already targeted changes its adjustment. |
| `exclude_locations` | Excludes a location. |
| `remove_locations` | Stops targeting or excluding a location. |
| `add_radius` | Targets a radius around a latitude and longitude, with an optional bid adjustment. |
| `remove_radius` | Removes a radius by criterion ID. |
| `location_setting` | Sets who counts as in a location: `PRESENCE_OR_INTEREST` or `PRESENCE`. |
| `add_languages`, `remove_languages` | Adds or removes a language. |

Google doesn't let a criterion's value or excluded flag change, so moving a location
between the included and excluded lists sends a removal and an add, in that order, in
one request. When a campaign's change removes a location or radius, all its location,
exclusion, and radius changes form one atomic group. If Google rejects an add at the send
that passed the dry run, the campaign keeps its locations, while other campaigns and
language changes still apply. A bid adjustment is a percent on the card and in the request, and the tool
compiles it to Google's modifier.

The tool refuses these before Google's dry run:

- Adding a language to a Search campaign. Google matches each ad's language on Search
  and rejects the criterion. A language left on a Search campaign from before can
  still be removed.
- A change that would leave a campaign that has locations with none, because its ads
  could then show anywhere. An add Google rejects or doesn't recognise doesn't count as
  a location left. This also covers Google's rule for Local Services Performance Max
  campaigns.
- A location or language key Google doesn't recognise.

Radius targets take coordinates, not an address. Google computes a point from an
address, so the read-back can't be matched to the request until that's confirmed
against a live account.

`operations/criteria.py` reads each campaign's criteria by type
(`read_campaign_targeting`) and returns them by edit key. An included and an excluded
place have different keys, so the edit seam sees a move as two changes.

While preparing the approval, the tool reads each campaign, reads Google's names, and
dry runs the rest through the edit seam. The trusted `_checks` display argument holds,
per campaign, what it targets now (up to 100 locations by name, with the total), the
problem that stops it, each item's problem, what's already set, and the live criteria
the request touches. The tool declares `changes` in `approval_review_fields`, so any
edit needs a new check. Approval plans against the criteria the operator saw, so the
edit seam refuses anything changed since as `CHANGED_SINCE_APPROVAL`. The tool also
reads each campaign again and applies the rules above to the live state, with nothing
sent for a campaign that fails them. One request makes at most 2,500 edits, because one
audit event holds 2,500 records.

The result has one row per campaign, setting, action, and outcome, with up to 10 item
names and a count, so it stays small at any request size. Audit records each change by
key, never the names of places.

### Negative keywords

`google_ads_update_negative_keywords` adds and removes negative keywords on campaigns,
ad groups, and negative keyword lists, and changes which campaigns use a list, in one
approval. Each entry names one target by `kind`:

| Kind | Target | Fields |
| --- | --- | --- |
| `campaign` | A campaign reference. | `add`, `remove` |
| `ad_group` | An ad group reference. | `add`, `remove` |
| `list` | A negative keyword list reference. | `add`, `remove`, `apply_to_campaigns`, `remove_from_campaigns` |
| `new_list` | The new list's name. | `add` and `apply_to_campaigns`, both needed |

Each keyword is `{text, match_type}`, with `EXACT`, `PHRASE`, or `BROAD`, at most 80
characters and 10 words. A new list goes in the account of its campaigns, because tool
arguments name an account only through references; a list's campaigns must be in its
own account. One call holds up to 100 targets, 1,000 keywords, and 1,000 campaign
changes.

`operations/negative_keyword_criteria.py` reads the targets, removed ones included,
with their negatives, each list's keywords and campaigns, and the account's list names.
Negatives are keyed by owner, match type, and lower-case text, because Google ignores
case. Existing targets go through the edit seam as criterion adds and removes; a
negative already there is `already_set` and a removal that isn't there is `not_found`,
without a write. Each new list, with its keywords and campaigns, goes through the build
seam in one atomic request. `joined_ledger` joins the two ledgers, so one audit record
names every change by key.

The tool refuses these before Google's dry run:

- A target that doesn't exist or has been removed, and a new list whose name is taken.
- A campaign that doesn't exist or has been removed, as a list's new campaign.
- A negative that would block a keyword the account bids on in the same campaign or ad
  group, or in a campaign that uses the list. It compares the keyword's own words: an
  exact negative matches them all, a phrase negative matches them in order, and a broad
  negative matches each word anywhere. A list keyword that would block a keyword in a
  campaign newly using the list is a problem on that campaign.

The trusted `_checks` display argument holds, per target, its name, status, problem, and
one row per change with its live resource name, its state (`change`, `already_set`, or
`not_found`), and its problem. The tool declares `entries` in `approval_review_fields`, so
any edit needs a new check. Approval plans against the rows the operator saw; a change
with no row is refused. The card can add campaigns, ad groups, and lists the agent didn't
propose; like any edit, they need **Check Changes**, and a target without a check is
refused.

The display result has one row per change with its outcome. The agent gets the counts
and only the changes that failed or are unconfirmed, up to 50.

### Search terms

`google_ads_optimise_search_terms` acts on a search terms report in one approval. The agent
reads `search_term_view` with `google_ads_run_report`, then passes the report's
`start_date` and `end_date` with up to 1,000 decisions. Each decision names the
`search_term`, the `ad_group` it matched in, an `action`, and a `match_type`:

| Action | Target | Fields |
| --- | --- | --- |
| `add_negative` | The matched ad group, its campaign, or a negative keyword list. | `level` (`ad_group`, `campaign`, or `list`), and `negative_list` for a list |
| `add_keyword` | The matched ad group, or another ad group in the same account. | `keyword_ad_group`, optional |

A term is at most 80 characters and 10 words, like any keyword. Two decisions can't add
the same criterion to the same place, and the date range is at most a year.

Before approval, `operations/read_search_terms.py` reads `search_term_view` for the
matched ad groups and the date range in one GAQL query per account, summing a term's rows,
and reads the keywords the keyword targets already bid on. Targets, negatives, lists, and
keywords that could be blocked come from `read_negative_keywords`. The card's clicks,
cost, and conversions come from that read, never from the agent's arguments. Every
decision is one criterion change on the edit seam (a negative on `campaignCriterion`,
`adGroupCriterion`, or `sharedCriterion`, and a keyword on `adGroupCriterion` with
`negative: false`), so one account's negatives and keywords go in one partial-failure
`googleAds:mutate`, reconciled per row and read back. A criterion already there is
`already_set` without a write.

The tool refuses these before Google's dry run:

- A term the report doesn't have for that ad group and date range.
- A matched ad group or target that doesn't exist or has been removed.
- A negative that would block a keyword the account bids on in its scope, or a keyword
  the same request adds. It uses the same word comparison as negative keywords.

The trusted `_checks` display argument holds, per decision key (matched ad group, action,
and lower-case term), the names, the term's status and figures, the live resource name,
the state, and the problem. The tool declares `decisions` in `approval_review_fields`, so
any edit needs a new check, and approval plans against the decision the operator saw: a
decision whose criterion differs from its check is refused. The display result has one
row per decision with the figures the approver saw and its outcome; the agent gets the
counts and up to 50 decisions that failed or are unconfirmed.

Reports declare the configured structured-result budget for transcript output
and preview only account row lists on overflow. Shared retrieval guidance
directs full-report calculations to the retained File through `read_table`
inside `run_code`.
Reports consume all `searchStream` batches without adding a GAQL `LIMIT` or
discarding rows. An explicit query `LIMIT` remains unchanged. The tool description tells
the agent to filter, order, and limit nearly every query, and to read search terms for one
date range ordered by cost with a `LIMIT` of at most 500, because an unlimited search terms
report fills the context. Large successful results
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

### Keyword additions

`google_ads_create_keywords` adds keywords on the edit seam, in one approval:
up to 50 ad groups and 1,000 keywords. Each entry in `entries` names a
`google_ads_ad_group` and its own keywords, each with `text` (at most 10
words), `match_type`, an optional `cpc_bid`, and an optional `final_url`, the
same keyword model Create Ad Groups uses. `status` is `PAUSED` by default. Each
keyword compiles to an add `CriterionChange` keyed by `keyword_key`.

`operations/keyword_additions.py` reads the ad groups with their campaigns and
bidding in one query. For the approval, the tool also reads the keywords the ad
groups bid on, then dry runs the rest. `_ad_groups`, keyed by ad group resource
name, carries the names, the campaign's strategy, whether it uses keyword bids,
the ad group's default bid when it does, and an ad group `problem`: missing,
removed, a removed campaign, or not a standard Search or Display ad group.
`_checks`, keyed by ad group, match type, and lower-cased text (the card can't
case fold), carries the keyword as checked and a `problem`:

- A keyword the ad group already has with that match type.
- A max CPC under a strategy that doesn't use keyword bids.
- Google's dry-run rejection, prefixed "Google says:".

Edits need a new check (`approval_review_fields`). After approval, a keyword
that differs from its check, or whose check showed a problem, is refused
without a request, and one added since approval is refused as changed since
approval. The card gets every keyword with its outcome (`added`,
`already_set`, `failed`, or `unverified`) and the new keyword's resource name;
the agent gets the counts and only the keywords that weren't added.

### Keyword changes

`google_ads_update_keywords` changes up to 500 positive keywords in one
approval, on the edit seam. Each entry in `changes` names a `google_ads_keyword`
reference and only the settings that change:

| Setting | Field path | Notes |
| --- | --- | --- |
| `cpc_bid` | `cpcBidMicros` | Account currency. `"none"` removes the keyword's own bid, so it uses its ad group's. |
| `final_urls`, `final_mobile_urls` | `finalUrls`, `finalMobileUrls` | Up to 10 each; an empty list clears them, so the ad's URLs apply. |
| `url_options` | `finalUrlSuffix`, `trackingUrlTemplate`, `urlCustomParameters` | As for campaigns; an empty value clears it. |
| `match_type` | `keyword.matchType` | `EXACT`, `PHRASE`, or `BROAD`. |

Status isn't a setting here: `google_ads_update_status` pauses and enables
keywords, and `google_ads_remove_objects` removes them.

Google can't change a keyword's match type. A new match type compiles to two
edits in one `atomic_group`: a `FieldChange` that pauses the keyword and a
`CriterionChange` that adds the same text with the new match type, the old
keyword's status, and its bid and URLs with the requested ones on top. The pause
compares every carried setting, so a keyword whose bid or URLs changed since
approval is refused and nothing is added. A match type equal to the live one is
never sent and reports `already_set`. Labels and the old keyword's history stay
with the paused keyword.

`operations/keyword_settings.py` reads each keyword with its ad group, campaign,
and campaign bidding in one query by resource name. For the approval, the tool
also reads the keywords the ad groups bid on (`read_ad_group_keywords`), then dry
runs the edits. The trusted `_checks` display argument, keyed by resource name,
carries the keyword's text, live match type, ad group and campaign names, the
campaign's strategy and the bids it uses, the `current` settings, the
`requested` settings the check covered, Google's `values` that approval plans
against, a `problem` (missing, removed, a removed ad group or campaign, or
Google's dry-run rejection prefixed "Google says:"), and per-setting
`problems`:

- A max CPC under a strategy that doesn't use keyword bids, naming the
  campaign's strategy. Removing a bid is always allowed.
- A new match type the ad group already has for the same text.

Edits on the card need a new check (`approval_review_fields`). After approval,
a keyword whose settings differ from its check, or whose check showed a
problem, is refused without a request. Each result row is one keyword with its
settings' **Before**, **Requested**, and **After**, the keyword's outcome, and,
for a new match type, the added keyword's resource name in `replacement`. The
card gets every keyword; the agent gets the counts and only the keywords that
didn't change.

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
registers with the apply and remove tools. Deleting a label is a `label`
removal in `google_ads_remove_objects`.

`google_ads_apply_labels` attaches 1 to 10 label references to 1 to 500
targets, and `google_ads_remove_labels` detaches them. Each target is an
explicit union tagged by `kind`: `campaign`, `ad_group`, or `keyword`, carrying
the matching scoped reference. Keywords are positive keywords only. The `ad`
kind is pending. The tools never accept raw resource
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
per label and target pair, ordered by type.
Account metadata requires a nonblank label and a valid currency code.

New Google cards build from the shared ads card kit in
`integrations/ads/components/`, which Meta also uses: `SettingRows`,
`SettingRow`, `SettingLine`, `StatusChoice`, `ChangeBanner`, `ChangeSummary`,
`AttentionLine`, `MoneyField`,
`EntityPicker`, `EntitySearch`, and the form controls (`ChoiceCards`, `SegmentedChoice`,
`Chip`, and the labelled fields). The kit depends on no provider package,
and dependency rules enforce that. `StatusChoice` is one plain line: Status, the
choice, and a note such as "Paused. Will not appear or spend until
activated." or "Active, pending approval. Will go live once approved by
Google." Campaign and ad group notes leave out approval. The older Google kit
(`GoogleAdsApprovalSection`, `GoogleAdsEntityCard`, `GoogleAdsBeforeAfter`,
`GoogleAdsOutcomeTable`) stays only for the tools plan 312 replaces and
keyword creation.

### Outcome evidence

Outcome vocabulary, token labels, lifecycle copy, and result envelopes have
separate modules. Device bid modifiers, recommendations, and positive-keyword creation
share `GoogleAdsOutcomeTable` and `GoogleAdsFailureTargets`. The table owns
outcome labels, stat order and tones, conditional detail and error columns,
and sample notices. Tool columns and result validation stay with each tool.
Keyword-creation sample envelopes use shared per-outcome count validation,
including truncated sample upper bounds.

### Approval composition

Approval summaries use `GoogleAdsApprovalSection` and `GoogleAdsEntityCard`.
Ad-group targets use `GoogleAdsEntityGroup`; approval scale uses one count
line instead of result stats.
Every write variant uses `googleAdsWriteCopy`; keep semantic overrides visible
in the presenter, including declined recommendation dismissal.
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
blocks, a `ParentTable` of campaigns when the items sit in more than one, and
the change table. Each campaign row counts its items, says whether the campaign
is on or off once the request runs, and names its account when the request
covers several; Cancel on it cancels all of its items, with one Undo. A click
on a campaign filters the change table to its items. Each summary line filters the
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
approval, as does Google's whole-request problem. The approve label counts ads
times ad groups.

After an edit to the ads, `adsNeedCheck` makes approval wait for **Check Changes**,
comparing the draft with the request the server last checked. `canCheckAds` holds
the check back while the card can already see a problem, to save a call to Google.
When Google couldn't be reached, the same control reads **Check Again**. A status
change needs no check. On every create card the control is the last thing in the card,
beside the approve button that waits on it.

The card (`components/create-ads-approval.tsx`) shows `StatusChoice`
(Paused or Active). With more than one ad it adds `ChangeSummary`
lines for a final URL and display paths that every ad shares, edited once;
Needs Attention with Cancel These N; and Cancelled with Restore. Then
`AttentionLine`, and the ad groups first, on the shared `ParentTable`: each
row is an ad group with its campaign, its ads, and its problems. A problem
counts against an ad group only when it names that ad group or the whole
ad (`problemsIn`), so a rejection in one ad group doesn't flag the others.
**Add Ad Group** above the table searches the account's ad groups, and the
chosen one joins the table with no ads yet. Clicking an ad group shows only
its ads in the `DataTable` below (All and Needs Attention tabs), with an add
line in its footer: **Use Another Ad Here** adds the ad group to one of the
request's other ads, and **New Ad** adds a blank one with the shared final
URL and paths. Clicking an ad's row opens it below (Previous and Next step
through the ad group's ads), naming the other ad groups it's created in,
with `SearchAdPreview` (a Google result in Google's light or dark colours,
named from the final URL's host; pinned assets in place, then the rest in
order), `TextAssetList` for headlines and descriptions (counters, pins, the
minimum, the first three until Show All), and link fields.

One ad can go in up to ten ad groups, so cancelling works per ad group
(`cancelInAdGroups`): Cancel on an ad's row takes it out of the selected
ad group only, Cancel on an ad group takes all of its ads out of it, and
Cancel These N takes each ad out of the ad groups its problems name, or out
of every one for a problem with the ad itself. An ad left in no ad group
leaves `ads`. The approval controls keep what was cancelled, and ad groups
added with no ads, through a check's redraw (`parseRetained`). Undo on an
ad group and Restore join each cancelled ad back to the request's ad with
the same copy (`restoreAdGroups`). Reloading the page loses them.

The result (`components/create-ads-outcome.tsx`) is one `DataTable` with Ad
Group, Headline 1, Status, Review, and Outcome. When nothing was created it
says so once with Google's reason, because the request is atomic.

### Create Ad Groups card

`lib/create-ad-groups.ts` parses the request with `_accounts` and `_checks`.
`adGroupRows` lists each ad group's problems: its name (empty, too long, repeated
in the request, or live in the campaign in any case), bids the campaign doesn't
accept, keyword limits and marks, each ad's copy, and Google's rejections. A
rejection applies only while its ad group has the same name and still holds the
rejected item. After the operator chooses another campaign, the campaign's rules
and rejections stop applying until they check it. Any problem blocks approval.
`adGroupsNeedCheck` and `canCheckAdGroups` make approval wait for **Check Changes**,
as on the Create Ads card, after an edit to the campaign or ad groups.

The card (`components/create-ad-groups-approval.tsx`) names the campaign's bidding
once, then shows `StatusChoice` and the campaign first, as a one-row `ParentTable`
with its ad group count and problems. Cancel on it cancels every ad group, and
Undo restores them. The tool takes one campaign, so **Change Campaign** above
the table opens an `EntityPicker` in place of an Add button. With more than one
ad group it adds `ChangeSummary`, with counts, Cancel These N, and Restore, and one
`DataTable` of ad groups with editable names. Clicking a row opens the ad group
below, in `SettingRows`: Name, Keywords, Ads, Negatives, and Bids. Keywords and
negatives use the shared `KeywordPaste` (one per line: `[exact]`, `"phrase"`, or
plain text for broad; parsing is in `integrations/ads/lib/keyword-notation.ts`).
Review opens a table for match types, click bids, and final URLs. A pasted keyword
keeps its bid and URL when its text and match type stay the same. Ads use
`AdCopyEditor`, shared with Create Ads. Inputs inside a table cell save when the
field loses focus, so typing doesn't redraw the table. The table, the ad group editor,
`AdGroupSummary`, and `ProblemList` live in `components/new-ad-groups.tsx`, shared with
Create Search Campaign. **Add Ad Group** adds one named "Ad Group N", with a blank ad that
starts from the first ad's links, up to 20 per request (`blankAdGroup`). The open ad group
is one bordered box with its rows inside. The ad group rules take an `AdGroupContext` (bid rules, live names,
Google's rejections, and whether an ad group must be able to serve), so both cards apply
the same rules.

The result (`components/campaign-build-outcome.tsx`, parsed by
`lib/campaign-build-result.ts` and shared with Create Search Campaign) has one row per kind
of object. When nothing was created, it says so with Google's reason, or lists the
reasons in a table when there are several. Google Ads links aren't shown, because
no deep-link helper exists yet.

### Create Search Campaign card

`lib/create-campaign.ts` parses the request with `_accounts` and `_checks`, keeping every
bidding strategy's fields in the draft so switching strategy and back keeps what was
entered; only the chosen strategy's fields are sent. The campaign's problems are its name,
budget, bidding fields, locations (none, too many, or unknown to Google), dates against the
checked date, negative keyword limits, and Google's rejections while the rejected location
or negative keyword is still there. A shared budget that belongs to one campaign is a
problem too. Ad groups use the shared rules with the new campaign's bidding
(`biddingRules`) and must have a keyword and an ad. Any problem blocks approval.
`campaignNeedsCheck` and `canCheckCampaign` make approval wait for **Check Changes** after
an edit to the campaign or ad groups, as on the other create cards.

The card (`components/create-campaign-approval.tsx`) shows `ChangeBanner` with the daily
budget and about a month's spend (30.4 days, Google's monthly charging limit), then
`StatusChoice`, then `SettingRows`: Name, Budget (an amount, or a shared budget from the
budget lookup), Bidding (`ChoiceCards` and the chosen strategy's fields), Locations (chips
for shown and excluded places, search or paste with `LocationPaste`, and Who Counts), and
More Settings (networks, dates, the EU political declaration, and campaign negatives with
`KeywordPaste`). The ad groups follow with `AdGroupSummary` and `NewAdGroups`, as on Create
Ad Groups, with the same Cancel These N and Restore. The approve button reads **Create
Campaign**.

### Update Targeting card

`lib/update-targeting.ts` parses `changes` with `_accounts` and `_checks`, and keeps
each entry as received so edits keep their fields. A campaign's problems apply while
its entry matches what Google last answered for; once edited, it waits for
**Check Changes** instead (`needsCheck`). Any problem blocks approval.

The card (`components/targeting-approval.tsx`) shows each change once:

- A note says what approving does now. Paused campaigns get a neutral note, because
  they show no ads until someone turns them on. `ChangeBanner` appears only when a
  campaign is on.
- With more than one campaign, a `ParentTable` of campaigns comes first, with an
  `AttentionLine` when any is blocked. Each row has its change count, what changes,
  its languages before and after, and Cancel or Undo. Rows are ordered by
  `campaignsByDifference`: blocked, then cancelled, then the least common change. A
  click on a campaign scopes the sections below to it: they show only its changes,
  edits and additions apply only to it (`editInScope`), and its problems show in an
  alert above them. With nothing selected, the sections show and edit every
  campaign's changes together. One campaign has no table, and its problems show
  without a click.
- **Where Ads Can Show** is one list of places, each marked **Adding**, **Excluding**,
  **Removing**, or **No Change**. Each added place has its own `BidAdjustment`, and ×
  cancels that change on every campaign shown. With more than one campaign, each row says how
  many it reaches. Eight or more places of one type collapse to one row with **Review**.
- **Add or Exclude a Location** opens the tools: search, `LocationPaste` (up to 500 lines
  at a time; lines Google doesn't recognise are skipped and counted, and a failed lookup
  keeps what it already found), and a distance around a place.
- **Languages** appears only when a campaign can take a language or one is changing, so
  it's hidden on Search campaigns with no language change.
- **Who Counts** holds the location setting.

Cancelling a campaign's last change moves it out of the request and into the approval
controls' retained state, so **Undo** restores it through a check's redraw. A selected
campaign that is cancelled shows a line with Undo in place of the sections. With every
campaign cancelled, the next location added starts them again from nothing
(`clearedChange`). Reloading the page loses cancelled campaigns.

The approve label names one location on one campaign ("Add France"), counts several
("Add 2 Locations"), and otherwise counts campaigns, leaving out blocked ones.

The result (`components/targeting-outcome.tsx`) is the standard `DataTable` result card,
as on Update Status: Campaign, Setting, Before, After, and Outcome, with tabs for All,
Changed, Already Set, Failed, and Unconfirmed when any, opening on Failed when anything
failed. The search result (`components/targeting-search-table.tsx`) has columns that
follow the kind.

### Update Negative Keywords card

`lib/negative-keywords.ts` parses `entries` with `_accounts` and `_checks`, and keeps
each entry as received. An edit rewrites only the lists it changes, so an untouched
target keeps the answers Google gave for it. A target's problems apply while its entry
matches what Google last answered for; once edited, it waits for **Check Changes**. Any
problem blocks approval.

The card (`components/negative-keywords-approval.tsx`) has two tables: **Add Negative
Keywords** (Added To) and **Remove Negative Keywords** (Removed From), each with one row
per change: the keyword or campaign, its match type, and its target. A campaign starting
or stopping a list sits in the matching table, and an Already in Place or Not There row
says it's skipped. One change reads as a sentence instead of a table. Tables show 10 rows
a page. From ten changes the card adds `ChangeSummary` (Already in Place, Not There to
Remove, and Needs Attention with **Cancel These**), and `AttentionLine`; selecting a line
filters whichever table holds its rows. From ten rows a table adds search, filter tabs
(per target when there's more than one), and a bulk bar that sets the match type or
cancels the selected rows. Match type edits in the row, and each row has **Cancel This
Change**. A new list left without keywords or campaigns leaves the request whole;
cancelled rows and targets stay in the approval controls' retained state, so **Undo**
restores them through a check's redraw. **Add Negative Keywords** opens a panel with
`NegativeTargetCombobox` (the targets as chips; typing searches campaigns, ad groups, and
negative keyword lists at once, and the list stays closed until then), quick links back
to request targets taken out, `KeywordPaste`, and an `EntityPicker` per list to use it
in another campaign.

The result (`components/negative-keywords-outcome.tsx`) splits the same way: Added
Negative Keywords (with a new list's creation and the campaigns starting a list) and
Removed Negative Keywords, each a standard `DataTable` of 10 rows a page with Negative
Keyword, Match Type, Added To or Removed From, and Outcome, tabs per outcome, opening on
Failed when that table has a failure.

### Optimise Search Terms card

`lib/search-terms.ts` parses `decisions` with `_accounts` and `_checks`, and keeps each
decision as received. A decision's problem applies while it matches what Google last
answered for; once edited, it waits for **Check Changes**, keeping the term's figures.
Any problem blocks approval.

The card (`components/search-terms-approval.tsx`) has a `ChangeBanner` with the cost of
the terms being blocked, and one `DataTable` sorted by cost: Search Term, Matched In,
Clicks, Cost, Conv., then Action, Match Type, and Target as inline selects. A negative's
target is its ad group, its campaign, or a list in the request; a keyword's is any ad
group in the request in the same account. From ten rows the card adds `ChangeSummary`
(Block as Negatives, Add as Keywords, Already Set, and Needs Attention with **Cancel
These**), `AttentionLine`, search, filter tabs, and a bulk bar that sets the action,
match type, or a negative's target, or cancels. An edit that would add the same
criterion twice keeps the first decision and cancels the other. Each row has **Cancel
This Change**, and cancelled decisions stay in the retained state, so **Undo** restores
them. The card can't add search terms the agent didn't propose.

The result (`components/search-terms-outcome.tsx`) is one `DataTable` with Search Term,
Action, Match Type, Target, Cost, and Outcome, tabs for Blocked, Added, Already Set,
Failed, and Unconfirmed, opening on Failed when anything failed.

### Update Campaigns card

`lib/update-campaigns.ts` parses `changes` with `_accounts` and `_checks`, and
keeps each entry as received so edits keep their reference. `campaignRows`
gives one row per campaign and setting, with the live value, the new value,
and a problem. A problem applies while the row's value matches what Google
last checked; an edited value waits for **Check Changes** instead
(`needsCheck`). Any problem blocks approval, and a row whose value equals the
live value is Already Set and isn't counted.

The card (`components/update-campaigns-approval.tsx`) shows the banner with the
count of changes, then each row as the live value, an arrow, and an inline
editor: an On/Off choice for networks, a date field for dates (an empty end date
means no end date), and a text field otherwise. Custom parameters are edited as
`key=value, key=value`. Bidding has its own editor (`components/bidding-editor.tsx`).
With one campaign, `BiddingChange` is a section beside the list of other settings: a
**Now** panel with the live strategy and its targets, and the new strategy as a labelled
select with each target as its own labelled field. A sentence says what the new bidding
does (`biddingSentence`), and that learning carries on when the strategy stays the same.
The bidding notes are listed under it. With many campaigns, `BiddingCell` puts the change on
one line with the notes under it, and an edit button opens the same fields in the row.
**Portfolio Strategy** opens an `EntityPicker` for `google_ads_bidding_strategy`. A
target-only request shows the live strategy with only its own targets. When the live
strategy can't take the target, the problem offers **Switch to** the strategy that does
(`targetFix`). Such a request is never Already Set and doesn't count as restarting
learning. `lib/campaign-bidding.ts` mirrors the server's card terms, writing money
canonically so an edit matches what Google checked. A Target Impression Share change
without a page position, share, and maximum click bid is a problem the card raises
itself, and Check Changes waits for it. The banner's title says Google's learning
restarts, with the count of campaigns, when a strategy changes. Its detail names the
account and its time zone. A sole change's prompt names only the campaign, such as
"Switch Praxis Agents | Search | UK to Target Impression Share." One campaign is a plain list of
its settings; more than
one is a `DataTable` with Campaign, Setting, Change, and Cancel columns. From
ten rows, a `ChangeSummary` line per setting filters the table, and the End
Date, Search Partners, and Display Expansion lines can set every campaign in the
line, as can the Bidding line for one shared target when every change in it is
on the same strategy; search, setting tabs, Needs Attention, and row selection with **Cancel
These Changes** appear too. Cancelled settings move into the approval controls'
retained state, so **Undo** restores them, and their campaign, through a
check's redraw. Text fields save on blur through the shared kit's
`CommittedInput`. Under the rows, **Add a Change** (`components/add-change.tsx`,
shared with Update Ad Groups) adds a setting the agent didn't propose
(`addableCampaignSettings`, `addedCampaignChanges`), starting at its live
value. Networks are offered only on channels that take them, a start date
only before the campaign starts in the account time zone, and bidding only
from a standard strategy, because a live portfolio has no reference to write
back. An added setting needs **Check Changes**. The approve label names a sole change ("Remove End Date",
"Turn Off Search Partners", "Switch to Maximise Conversions", "Change Target")
and otherwise counts the changes that will run.

The result (`components/update-campaigns-outcome.tsx`) is the standard
`DataTable` result card: Campaign, Setting, Before, After, and Outcome, with the
edit seam's outcome tabs from `lib/edit-outcomes.ts`, which Update Status and
Update Targeting share. After is blank when Google's reply couldn't be read back.

### Update Ad Groups card

`lib/update-ad-groups.ts` parses `changes` with `_accounts` and `_checks` and
gives one row per ad group and setting (`adGroupRows`), with the same rules as
Update Campaigns: a problem applies while the row matches what Google checked,
an edit waits for **Check Changes**, and a row at its live value is Already
Set. A removed target is written back as `"none"`, and URL settings go inside
`url_options`.

The card (`components/update-ad-groups-approval.tsx`) shows the banner with the
count of changes. One ad group is a list under a line naming its campaign and
the campaign's strategy. Every setting is one line: the live value, an
arrow, and an inline editor. Bids and targets take an amount with the
currency symbol, or a percentage for target ROAS, and an empty target follows
the campaign. Ad rotation is an Optimise or Rotate Evenly choice. More than one ad group is a `DataTable`
with Ad Group (and its problem), Campaign (and its strategy), Setting, Change,
and Cancel columns. From ten rows, a `ChangeSummary` line per setting filters
the table. The Default Max CPC and Target CPA lines take a percentage that
changes every amount in the line from its live value, rounded to the
currency's smallest unit (`scaledMoney`). The Ad Rotation line sets every ad
group, and search, tabs, Needs Attention, and **Cancel These Changes** appear,
as on Update Campaigns. Under the rows, **Add a Change** adds a setting the agent didn't propose
(`addableSettings`, `addedAdGroupChanges`), starting at its live value, with
an **Ad Group** choice when there are several. Bids and targets are offered
only where the campaign's strategy uses them, and a name or CPC bid needs a
live value to start from. An added setting needs **Check Changes**, like any
edit. The approve label names a sole change ("Change Max
CPC", "Remove Target ROAS") and otherwise counts the changes.

The result (`components/update-ad-groups-outcome.tsx`) is the standard
`DataTable` result card: Ad Group, Setting, Before, After, and Outcome, with
the edit seam's outcome tabs and `editOutcomeSummary` from
`lib/edit-outcomes.ts`.

### Update Keywords card

`lib/update-keywords.ts` follows Update Ad Groups: one row per keyword and
setting (`keywordRows`), a problem that applies while the row matches what
Google checked, **Check Changes** after an edit, and Already Set for a row at
its live value. A removed bid is written back as `"none"`, URL lists as lists,
and URL options inside `url_options`. `replacesKeyword` marks a match type row
that differs from the live match type.

The card (`components/update-keywords-approval.tsx`) shows the banner with the
count of changes. When more than one keyword changes, the ad groups come
first in `ParentTable` (Keywords and Changes), and a click filters the change
table to one ad group; Cancel on an ad group cancels all of its changes. When
a match type changes, the card notes that the keyword is
paused and the same text added with the new match type, together or not at
all. Each such row says which keyword is paused and which is added. One keyword
is a list under a line naming its match type, ad group, campaign, and the
campaign's strategy. More than one is a `DataTable` with Keyword (its match type
and problem), Ad Group (its campaign and strategy), Setting, Change, and Cancel
columns. Match type is an Exact, Phrase, or Broad choice; Max CPC takes an
amount, and an empty bid uses the ad group's; URLs are separated by spaces;
custom parameters are `key=value` pairs. From ten rows, the Match Type summary
line sets every match type, the Max CPC line takes a percentage
(`scaledMoney`), and the bulk bar sets the match type of the selected rows.
**Add a Change** offers Max CPC only where the campaign's strategy uses keyword
bids. The approve label names a sole change ("Change Match Type", "Remove Max
CPC") and otherwise counts the changes.

The result (`components/update-keywords-outcome.tsx`) is the standard edit
seam result card: Keyword, Ad Group, Setting, Before, After, and Outcome. A
match type row whose replacement was added says the old keyword was paused.

### Update Budgets card

`lib/update-budgets.ts` parses `changes` with `_accounts` and `_checks` and
gives one row per change (`budgetRows`). A problem applies while the row
matches what Google checked, an edit waits for **Check Changes**, and a row
at its live values is Already Set. Cancelled changes are kept in the
approval controls' retained state for **Undo**.

The card (`components/update-budgets-approval.tsx`) shows the banner with the
change to daily spending and about a month of it (30.4 days, Google's monthly
charging limit). The `DataTable` has Campaign or Budget (with its problem,
and the campaigns a shared budget funds), Budget (Own, Shared with its
campaign count, or the move with **Choose Another** to pick a different
shared budget), Daily Amount (the live amount, an arrow, and an inline
amount, plus a Standard or Accelerated choice when delivery changes), Change,
Spent This Month, Month at New Amount (spend so far plus the amount for each
day left), Est. Monthly, and Cancel. From ten rows, `ChangeSummary` lines for
Raise, Lower, Shared, Move, and Needs Attention filter the table; the Raise
line takes a percentage that changes every raised amount from its live value
(`scaledMoney`). Selected rows can take one amount, a percentage, or
**Cancel These Changes**.

The result (`components/update-budgets-outcome.tsx`) is the standard
`DataTable` result card: Campaign or Budget, Setting, Before, After, and
Outcome, with the edit seam's outcome tabs.

### Remove Items card

`lib/remove-objects.ts` parses `items` with `_accounts` and `_checks` and
gives one row per item (`removalRows`) with what it takes with it as text,
such as "92 keywords, 6 ads", "Funds 1 campaign", or "Comes off 3 campaigns".
Counts at the read bound show "+". A problem blocks approval until the item is
cancelled, since there's nothing to edit; cancelled items are kept for
**Undo**.

The card (`components/remove-objects-approval.tsx`) opens with
`ChangeBanner` in its danger tone, "Removal can't be undone", with the item
count and the ads, keywords, and ad groups that campaign and ad group
removals take with them. The `DataTable` has Item (with its ad group for ads
and keywords, and its problem), Kind, Campaign, Also Removes, and Cancel.
From ten rows, `ChangeSummary` has one line per kind and Needs Attention
with **Cancel These N**, tabs filter by kind, and selected rows take
**Cancel These Changes**. The approve label counts the items, such as
"Remove 98 Items".

The result (`components/remove-objects-outcome.tsx`) is the standard
`DataTable` result card: Item, Kind, Campaign, Also Removed, and Outcome,
with Removed, Already Removed, Failed, and Unconfirmed tabs, opening on
Failed when any failed.

### Update Ads card

`lib/update-ads.ts` parses `changes` with `_accounts` and `_checks`, reads each
entry's edits the way the server does, and runs the same merge
(`mergedCopy`), so the card shows the copy that will be sent and raises the
merge problems, empty or long text, long paths, and a bad final URL itself.
Google's `problem` and `problems` apply while the ad's edits match what was
checked (`editsSignature`); an edit waits for **Check Changes** instead
(`adsNeedCheck`), and Check Changes waits until the card's own problems are
fixed (`canCheckAds`). An ad whose merge leaves it as it is shows Already Set.

The card (`components/update-ads-approval.tsx`) opens with a banner saying
edited ads go back through Google's review. One ad shows **Now** and **After**
search result previews (`SearchAdPreview`) over an editor of the after copy:
`TextAssetList` for headlines and descriptions with counters and pins, and the
final URL and paths. `editsFor` turns the editor's copy back into edits: an
edited headline is a removal and an add that the merge puts back in the same
place, keeping its pin. With several ads that share one edit, a **Replace**
and **With** pair per swapped headline or description changes every ad at
once, with one ad's Now and After previews under it. A `DataTable` lists the
ads (Ad, Ad Group, Campaign, and the headline count before and after), and a
row opens that ad's editor; editing one ad takes it out of the shared edit.
From ten ads, a `ChangeSummary` with Needs Attention and **Cancel These**,
search, and row selection appear. Cancelled ads move into the approval
controls' retained state, so **Undo** restores them through a check's redraw.
The approve label counts the ads that change ("Update 3 Ads").

The result (`components/update-ads-outcome.tsx`) is the standard `DataTable`
result card: Ad, Ad Group, Before (the text taken out), After (the text put
in), and Outcome. A changed ad still in Google's review shows In Review, and a
disapproved one shows Disapproved.

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

### Add Keywords card

`lib/create-keywords.ts` reads the entries, `_ad_groups`, and `_checks`. A
keyword's problem is the card's own (a max CPC that isn't an amount, a URL that
isn't a web address), then its ad group's, then the one Google gave for the
keyword as checked. Any edit, or an ad group the check hasn't seen, needs
**Check Changes**.

The card (`components/create-keywords-approval.tsx`) follows rule 10 of plan
303's tool model. **Add Ad Group** above the ad groups opens a search of the
account (`AdGroupCombobox`), and the chosen ad group joins them with no
keywords. The ad groups are in `ParentTable`: Keywords, Bid (the default bid,
or the strategy where keyword bids aren't used), and Problems. Clicking one
shows its keywords in the table below: Keyword with its problem, Match Type,
Max CPC where the campaign's bidding uses it, Final URL from the column
chooser, and Cancel. The table's footer has a line that adds a keyword with its
match type, or several pasted one per line in Google's notation. Cancelling an
ad group's last keyword cancels the ad group, and Undo restores it. From ten
keywords the change summary appears: a max CPC for every keyword, and Needs
Attention with Cancel These N. The result is one table:
Keyword, Match Type, Ad Group, Bid, and Outcome.

### Parent tables

`ParentTable` lists the campaigns, ad groups, or lists a card changes, above
the table of the changes in them. Each row has the parent's name, where it sits,
the caller's columns, and Cancel or Undo for all of its changes. A click
selects the parent and the card filters the changes to it. From ten rows it
gets search and a Needs Attention tab. A caller can draw its own cells with
`renderCell`. Add Keywords, Update Keywords, Update Targeting, and Update
Status use it.

## Live QA record

The operator tested the new write tools in the running app against live
accounts from 2026-11-08 to 2026-11-10, at the commits of the day and
before 305 E was committed. Most tests ran in a paused campaign of the test
account; the search term tests ran on two client accounts. The record below
comes from the conversations and the audit log in the local database, keyed
by conversation ID. Check numbers are those of
[plan 338](../../plans/google-ads/338-google-ads-live-qa.md) C.

| Check | Result | What happened |
| --- | --- | --- |
| 1. Time zone on the card | Passed | An approval in `c6324d66` failed before the connection was refreshed. Every write after the refresh ran. |
| 2. Status changes | Passed in part | `244b1251`: an ad group and an ad paused, then enabled, each read back. Keywords and an `already_set` reply weren't tried. |
| 3. Create ads | Passed in part | `f2458033`: two paused ads in one ad group, read back in review. A placeholder landing page was disapproved as prohibited, correctly. Ads in two ad groups and the 31-character block weren't tried. |
| 4. Create ad groups | Passed in part | `ab802fc2`: three ad groups, nine keywords, and six ads in one request. The CPC bid refusal wasn't tried. |
| 5. Ad group and its ad in one atomic request | Passed | `ab802fc2` and `9f27e98d` created new ad groups and their ads in one request each. |
| 6. Campaign build | Passed | `9f27e98d`: a paused Search campaign with its budget, two locations, two ad groups (one added on the card), seven keywords, six negatives, and two ads, read back. |
| 7. Rejected build leaves nothing | Not run for a campaign | Rejected ad creations in `244b1251` and `f2458033` left nothing behind (`NOTHING_CREATED`). |
| 8 to 10. Check Changes and card driving | Not recorded | The operator edited cards in several tests (an ad group on Create Ads, status on Create Ad Groups, an ad group on Create Campaign, Target Impression Share values, location bid adjustments), and the edited values were what ran. |
| 11. Campaign settings | Passed | `bae50edc`: name, an end date set then removed, final URL suffix, tracking template, and custom parameters set then cleared, and both networks on then off, each read back. |
| 12. Bidding switch | Passed in part | `bae50edc`: Maximise Clicks to Target Impression Share and back, then a cap cleared. Manual CPC to Maximise Conversions and the target ROAS refusal weren't tried. |
| 13. Target Impression Share after the mask fix | Passed | `bae50edc`: the switch that failed before 9c94f931 ran after it. |
| 14. Search for locations and languages | Passed | `93477bfe`: language names and France found. Cities weren't searched by name. |
| 15. Location changes in one approval | Passed in part | `93477bfe`: France added with a −10% adjustment and a city excluded in one approval. A language on a Search campaign is correctly not offered. |
| 16 to 18. Swap, radius by coordinates, radius by address | Not run | |
| 19. Negative keywords | Passed | `7c6fa4e9`, through Code Mode: 302 negatives across a campaign, an ad group, and a new list; the list applied to the campaign and detached; duplicate adds reported `already_set` and missing removals `not_found`; everything removed again. |
| 20. Negative blocking a keyword | Not run | |
| 21. Search terms | Passed in part | `0f4c4b66` and `f7fe7886`: six and two negatives from search terms on two client accounts. Keyword adds and cost against the Google Ads UI weren't recorded. |
| 22. Ad edits | Passed in part | `f399543e`: a headline added to two paused ads, updated in place through `AdService` and read back, with review status `REVIEWED` and approval `APPROVED` straight after. A swap, a pin, the two-headline refusal, and an enabled ad weren't tried. |

Faults the tests found:

- Google refuses a mask on a bidding field with subfields set. Fixed in
  9c94f931 (305 B).
- The ad group picker offered ad groups under removed campaigns, which Google
  refused at the send after passing the dry run (`244b1251`). Fixed in 304 A:
  entity lists leave out removed objects and their children.
- Large Code Mode approvals never reached the card, and runs were abandoned
  when their lease expired (`8127ab76`, `5839faeb`). The preview locked the
  run, and concurrent reads failed with "This session is provisioning a new
  connection". Fixed in 0be242be; plan 341 removes the repeated token lookups
  behind it.
- The agent can't tell when the operator changed its proposal on the card. In
  `ab802fc2` the operator chose Launch; the agent reported that Google had
  ignored its paused request and paused all nine objects again. In
  `93477bfe` it tried to undo a bid adjustment and an exclusion the operator
  had added, which the operator declined. See FOLLOW_UPS.

Left in the test account: an empty, unlinked negative keyword list from
`7c6fa4e9`. Check 25 removes it.
