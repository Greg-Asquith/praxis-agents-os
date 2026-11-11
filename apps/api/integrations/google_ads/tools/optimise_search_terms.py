# apps/api/integrations/google_ads/tools/optimise_search_terms.py

"""Approval-only tool that blocks search terms as negatives or adds them as keywords."""

import asyncio
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext, ToolReturn

from core.exceptions.integration import IntegrationError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets

from ..client import GoogleAdsClient
from ..operations.edits import CriterionChange, Edit, EditResult, prepare_edits
from ..operations.mutation_outcomes import GoogleAdsMutationLedger
from ..operations.negative_keyword_criteria import (
    BidKeyword,
    BlockedKeywords,
    LiveNegatives,
    read_negative_keywords,
)
from ..operations.read_search_terms import (
    SearchTermStats,
    read_ad_group_keywords,
    read_search_terms,
    search_term_key,
)
from .schemas.search_terms import (
    MAX_SEARCH_TERM_DECISIONS,
    GoogleAdsOptimiseSearchTermsOutput,
    GoogleAdsOptimiseSearchTermsRequest,
    GoogleAdsSearchTermDecision,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditPlan, run_approved_edits
from .utils.money import micros_to_money
from .utils.mutation_evidence import (
    google_ads_account_target,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "optimise_search_terms"
_FAMILY = "search_terms"
# One row per decision with its names and figures, for the most a call can carry.
_MAX_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_OUTCOMES = 50

_NOUNS = {"campaign": "campaign", "ad_group": "ad group", "list": "negative keyword list"}
_MATCHED_GONE = "The ad group this term matched in no longer exists in Google Ads."
_NOT_IN_REPORT = "Not in the search terms report for {start} to {end} in {ad_group}."
_GONE = "This {noun} no longer exists in Google Ads."
_REMOVED = "This {noun} has been removed, so it can't change."
_BLOCKS = "Blocks “{keyword}”, a keyword you bid on in {ad_group}."
_BLOCKS_NEW = "Blocks “{keyword}”, which this request adds as a keyword in {ad_group}."


def _edit(
    decision: GoogleAdsSearchTermDecision, before: str | None, refused: str | None
) -> CriterionChange:
    """Compiles one decision to the criterion it adds to its target."""
    target = decision.target
    keyword = {"text": decision.search_term, "matchType": decision.match_type}
    if decision.action == "add_keyword":
        resource = "adGroupCriterion"
        body = {"adGroup": target, "status": "ENABLED", "negative": False, "keyword": keyword}
    elif decision.level == "campaign":
        resource = "campaignCriterion"
        body = {"campaign": target, "negative": True, "keyword": keyword}
    elif decision.level == "ad_group":
        resource = "adGroupCriterion"
        body = {"adGroup": target, "negative": True, "keyword": keyword}
    else:
        resource = "sharedCriterion"
        body = {"sharedSet": target, "keyword": keyword}
    return CriterionChange(
        resource=resource,
        action="add",
        key=decision.write_key,
        owner=target,
        criterion=body,
        before=before,
        refused=refused,
    )


@dataclass(frozen=True, slots=True)
class _Live:
    """One account's targets, criteria, and search term figures."""

    negatives: LiveNegatives
    keywords: Mapping[str, str]
    terms: Mapping[str, SearchTermStats]

    def before(self, decision: GoogleAdsSearchTermDecision) -> str | None:
        criteria = self.keywords if decision.action == "add_keyword" else self.negatives.criteria
        return criteria.get(decision.write_key)

    def values(self) -> dict[str, dict[str, Any]]:
        """Returns every criterion by edit key, for the edit seam."""
        return {
            **self.negatives.values(),
            **{key: {"resourceName": name} for key, name in self.keywords.items()},
        }

    def stats(self, decision: GoogleAdsSearchTermDecision) -> SearchTermStats | None:
        return self.terms.get(search_term_key(decision.matched_in, decision.search_term))

    def name(self, resource_name: str, fallback: str) -> str:
        owner = self.negatives.owners.get(resource_name)
        return owner.name if owner else fallback


@dataclass(frozen=True, slots=True)
class _Problems:
    """Finds what stops each decision, against what's live and what the request adds."""

    live: _Live
    request: GoogleAdsOptimiseSearchTermsRequest
    blocked: BlockedKeywords
    proposed: BlockedKeywords

    def of(self, decision: GoogleAdsSearchTermDecision) -> str | None:
        owners = self.live.negatives.owners
        matched = owners.get(decision.matched_in)
        if matched is None or matched.status == "REMOVED":
            return _MATCHED_GONE
        if self.live.stats(decision) is None:
            return _NOT_IN_REPORT.format(
                start=_day(self.request.start_date),
                end=_day(self.request.end_date),
                ad_group=matched.name,
            )
        noun = "ad group" if decision.action == "add_keyword" else _NOUNS[decision.target_kind]
        target = owners.get(decision.target)
        if target is None:
            return _GONE.format(noun=noun)
        if target.status == "REMOVED":
            return _REMOVED.format(noun=noun)
        return self._blocks(decision) if decision.action == "add_negative" else None

    def _blocks(self, decision: GoogleAdsSearchTermDecision) -> str | None:
        if decision.level == "ad_group":
            campaigns, ad_group = set[str](), decision.target
        elif decision.level == "campaign":
            campaigns, ad_group = {decision.target}, None
        else:
            campaigns = set(self.live.negatives.list_campaigns.get(decision.target, ()))
            ad_group = None
        scope = {"campaigns": campaigns, "ad_group": ad_group}
        term, match_type = decision.search_term, decision.match_type
        if hit := self.blocked.first(term, match_type, **scope):
            return _BLOCKS.format(keyword=hit.text, ad_group=hit.ad_group_name)
        if hit := self.proposed.first(term, match_type, **scope):
            return _BLOCKS_NEW.format(keyword=hit.text, ad_group=hit.ad_group_name)
        return None


def _day(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def _proposed_keywords(
    live: _Live, decisions: Sequence[GoogleAdsSearchTermDecision]
) -> BlockedKeywords:
    """The keywords this request adds, which a negative in the same request mustn't block."""
    keywords = []
    for decision in decisions:
        if decision.action != "add_keyword":
            continue
        reference = decision.keyword_ad_group or decision.ad_group
        campaign = f"customers/{reference.customer_id}/campaigns/{reference.campaign_id}"
        name = live.name(decision.target, reference.label)
        keywords.append(BidKeyword(campaign, decision.target, name, decision.search_term))
    return BlockedKeywords(keywords)


async def _read_live(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsOptimiseSearchTermsRequest,
    decisions: Sequence[GoogleAdsSearchTermDecision],
    *,
    checking: bool,
) -> _Live:
    """Reads the account; `checking` adds keywords bid on and search term figures for the card."""
    customer_id, login = entry.external_id, login_customer_id(entry)
    matched = sorted({decision.ad_group.ad_group_id for decision in decisions})
    keyword_targets = sorted(
        {
            (decision.keyword_ad_group or decision.ad_group).ad_group_id
            for decision in decisions
            if decision.action == "add_keyword"
        }
    )
    campaigns = sorted(
        {decision.ad_group.campaign_id for decision in decisions if decision.level == "campaign"}
    )
    lists = sorted(
        {
            decision.negative_list.shared_set_id
            for decision in decisions
            if decision.negative_list is not None
        }
    )

    async def terms() -> dict[str, SearchTermStats]:
        if not checking:
            return {}
        return await read_search_terms(
            client,
            customer_id=customer_id,
            login_customer_id=login,
            ad_group_ids=matched,
            start_date=request.start_date,
            end_date=request.end_date,
        )

    negatives, keywords, figures = await asyncio.gather(
        read_negative_keywords(
            client,
            customer_id=customer_id,
            login_customer_id=login,
            campaign_ids=campaigns,
            ad_group_ids=sorted({*matched, *keyword_targets}),
            shared_set_ids=lists,
            list_campaign_ids=(),
            named_campaign_ids=sorted({decision.ad_group.campaign_id for decision in decisions}),
            check_keywords=checking,
        ),
        read_ad_group_keywords(
            client, customer_id=customer_id, login_customer_id=login, ad_group_ids=keyword_targets
        ),
        terms(),
    )
    return _Live(negatives, keywords, figures)


async def google_ads_optimise_search_terms(
    ctx: RunContext[RuntimeDeps],
    start_date: Annotated[
        date, Field(description="First day of the search terms report the decisions came from.")
    ],
    end_date: Annotated[date, Field(description="Last day of that report.")],
    decisions: Annotated[
        list[GoogleAdsSearchTermDecision],
        Field(
            min_length=1,
            max_length=MAX_SEARCH_TERM_DECISIONS,
            description="One entry per search term and action, in the ad group it matched in.",
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    request = validated_request(
        GoogleAdsOptimiseSearchTermsRequest,
        {"start_date": start_date, "end_date": end_date, "decisions": decisions},
    )
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_account: dict[str, list[GoogleAdsSearchTermDecision]] = defaultdict(list)
    for decision in request.decisions:
        by_account[decision.customer_id].append(decision)

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        account = by_account[entry.external_id]

        async def plan(_client: GoogleAdsClient) -> EditPlan:
            edits = [_approved_edit(decision, shown.get(decision.key)) for decision in account]
            return edits, _pending_detail(entry, account)

        async def result(client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            return _result(entry, account, shown, applied.ledger)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_optimise_search_terms",
            operation=_OPERATION,
            family=_FAMILY,
            plan=plan,
            read=lambda client: _reader(client, entry, request, account),
            result=result,
        )

    references = [
        reference
        for decision in request.decisions
        for reference in (decision.ad_group, decision.negative_list, decision.keyword_ad_group)
        if reference is not None
    ]
    results = await run_context_targets(
        ctx, binding=GOOGLE_ADS_WRITE_BINDING, references=references, operation=operation
    )
    return split_fan_out_tool_return(results)


def _approved_edit(decision: GoogleAdsSearchTermDecision, check: Any) -> CriterionChange:
    """Plans against what the approver saw, so `apply_edits` refuses anything changed since.

    A decision the card changed is sent only once Google checked it.
    """
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("key") != decision.write_key
    ):
        return _edit(decision, None, NOT_SHOWN)
    before = check.get("before")
    problem = check.get("problem")
    return _edit(
        decision,
        before if isinstance(before, str) else None,
        problem if isinstance(problem, str) else None,
    )


def _reader(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    request: GoogleAdsOptimiseSearchTermsRequest,
    decisions: Sequence[GoogleAdsSearchTermDecision],
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await _read_live(client, entry, request, decisions, checking=False)
        return live.values()

    return read


def _pending_detail(
    entry: ResolvedContextEntry, decisions: Sequence[GoogleAdsSearchTermDecision]
) -> PendingIntegrationOperationDetail:
    groups: dict[tuple[str, str], list[IntegrationOperationIntent]] = defaultdict(list)
    for decision in decisions:
        groups[decision.action, decision.target_kind].append(
            IntegrationOperationIntent(fields={"object": decision.write_key})
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{action}:{kind}",
                action="add",
                entity_type=f"google_ads_search_term_{action.removeprefix('add_')}",
                items=items,
            )
            for (action, kind), items in groups.items()
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    decisions: Sequence[GoogleAdsSearchTermDecision],
    shown: Mapping[str, Any],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    """Returns every row for the card, and the counts with what didn't happen for the agent."""
    parents = {dict(parent.identity)["object"]: parent for parent in ledger.parents}
    outcomes: list[dict[str, Any]] = []
    for decision in decisions:
        parent = parents[decision.write_key]
        effect = parent.effects[0] if parent.effects else None
        if parent.decision == "skipped":
            outcome = "already_set"
        elif effect is None or effect.outcome == "unverified":
            outcome = "unverified"
        else:
            outcome = "added" if effect.outcome == "applied" else "failed"
        outcomes.append(
            {
                **_figures(decision, shown.get(decision.key)),
                "search_term": decision.search_term,
                "action": decision.action,
                "match_type": decision.match_type,
                "target_kind": decision.target_kind,
                "outcome": outcome,
                "error_code": effect.error_code if effect else None,
                "message": effect.message if effect else None,
            }
        )
    counts = Counter(
        f"{row['action'].removeprefix('add_')}s_added"
        if row["outcome"] == "added"
        else row["outcome"]
        for row in outcomes
    )
    totals = {
        key: counts.get(key, 0)
        for key in ("negatives_added", "keywords_added", "already_set", "failed", "unverified")
    }
    missed = [row for row in outcomes if row["outcome"] in {"failed", "unverified"}]
    base = {
        "account_id": entry.external_id,
        "currency": account_facts(entry).currency,
        "counts": totals,
    }
    return {
        "display_result": {**base, "outcomes": outcomes, "outcomes_truncated": False},
        "model_result": {
            **base,
            "outcomes": missed[:_MAX_MODEL_OUTCOMES],
            "outcomes_truncated": len(missed) > _MAX_MODEL_OUTCOMES,
        },
    }


def _labels(decision: GoogleAdsSearchTermDecision) -> dict[str, str]:
    """The names the agent's references carry, for when Google's names are unknown."""
    campaign = decision.ad_group.scope_label or ""
    target = decision.negative_list or decision.keyword_ad_group or decision.ad_group
    return {
        "target_name": campaign or target.label if decision.level == "campaign" else target.label,
        "campaign_name": campaign,
        "ad_group_name": decision.ad_group.label,
    }


def _figures(decision: GoogleAdsSearchTermDecision, check: Any) -> dict[str, Any]:
    """The names and Google's figures the approver saw, or the references' labels."""
    seen = check if isinstance(check, Mapping) else {}
    names = {key: str(seen.get(key) or value) for key, value in _labels(decision).items()}
    return {
        **names,
        "clicks": seen.get("clicks"),
        "cost": seen.get("cost"),
        "conversions": seen.get("conversions"),
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts, and per decision Google's figures, the problems, and a dry run."""
    request = GoogleAdsOptimiseSearchTermsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsSearchTermDecision]] = defaultdict(list)
    for decision in request.decisions:
        by_account[decision.customer_id].append(decision)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, decisions in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), request, decisions))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    request: GoogleAdsOptimiseSearchTermsRequest,
    decisions: Sequence[GoogleAdsSearchTermDecision],
) -> dict[str, dict[str, Any]]:
    """Reads one account and dry runs its decisions; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await _read_live(client, entry, request, decisions, checking=True)
        problems = _Problems(
            live,
            request,
            BlockedKeywords(live.negatives.bid_keywords),
            _proposed_keywords(live, decisions),
        )
        planned = {
            decision.key: (live.before(decision), problems.of(decision)) for decision in decisions
        }
        google = await _dry_run(client, entry, decisions, planned)
    except (IntegrationError, LookupError):
        return {decision.key: {"unavailable": True} for decision in decisions}
    return {
        decision.key: _check(decision, live, *planned[decision.key], google)
        for decision in decisions
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    decisions: Sequence[GoogleAdsSearchTermDecision],
    planned: Mapping[str, tuple[str | None, str | None]],
) -> dict[str, str]:
    """Returns Google's reason for each decision it would reject, by write key."""
    edits = [_edit(decision, *planned[decision.key]) for decision in decisions]
    values = {edit.key: {"resourceName": edit.before} for edit in edits if edit.before}

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return values

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=edits,
        read=read,
        operation=_OPERATION,
    )
    return {
        edit.key: f"Google says: {sent.refused}"
        for edit, sent in zip(edits, prepared, strict=True)
        if sent.refused and edit.refused is None
    }


def _check(
    decision: GoogleAdsSearchTermDecision,
    live: _Live,
    before: str | None,
    problem: str | None,
    google: Mapping[str, str],
) -> dict[str, Any]:
    """Builds the card's view of one decision, and the live state approval plans against."""
    stats = live.stats(decision)
    matched = live.negatives.owners.get(decision.matched_in)
    campaign = matched.campaign if matched and matched.campaign else ""
    labels = _labels(decision)
    return {
        "unavailable": False,
        "key": decision.write_key,
        "campaign_name": live.name(campaign, labels["campaign_name"]),
        "ad_group_name": live.name(decision.matched_in, labels["ad_group_name"]),
        "target_name": live.name(decision.target, labels["target_name"]),
        "term_status": stats.status if stats else None,
        "clicks": stats.clicks if stats else None,
        "impressions": stats.impressions if stats else None,
        "cost": micros_to_money(stats.cost_micros) if stats else None,
        "conversions": stats.conversions if stats else None,
        "before": before,
        "state": "already_set" if before else "change",
        # Nothing is sent for a criterion already in place, so nothing can stop it.
        "problem": None if before else problem or google.get(decision.write_key),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_optimise_search_terms",
    function=google_ads_optimise_search_terms,
    description=(
        "Act on Google Ads search terms in one approval: block each as a negative keyword or "
        "add it as a keyword. First read search_term_view with google_ads_run_report for a "
        "date range, ordered by cost with a LIMIT of at most 500, then pass that "
        "start_date and end_date with up to 1,000 decisions. Each "
        "decision names the search_term, the ad_group it matched in, an action "
        "(add_negative or add_keyword), and a match_type (EXACT, PHRASE, or BROAD). "
        "add_negative needs a level: ad_group (the matched ad group), campaign (its "
        "campaign), or list (with negative_list). add_keyword goes in the matched ad group, "
        "or keyword_ad_group in the same account. The card shows each term's clicks, cost, "
        "and conversions as Google reports them for the date range. A term already a keyword "
        "or negative there is reported already_set without a change. A term the report "
        "doesn't have, or a negative that would block a keyword bid on, is refused."
    ),
    provider="google_ads",
    label="Optimise Google Ads Search Terms",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=GoogleAdsOptimiseSearchTermsOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsOptimiseSearchTermsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("decisions",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Optimising Search Terms",
        completed_label="Optimised Search Terms",
        failed_label="Couldn't Optimise Search Terms",
        approval_title="Optimise Search Terms",
        approval_prompt="The agent wants to block some search terms and add others as keywords.",
        approve_label="Approve & Apply",
        arg_fields=(
            ToolFieldPresentation(
                key="decisions",
                label="Search Terms",
                editable=True,
                format="structured",
                # The first kind authorises a review; the other is the lists' kind.
                entity_kinds=("google_ads_ad_group", "google_ads_shared_set"),
            ),
            ToolFieldPresentation(key="start_date", label="From"),
            ToolFieldPresentation(key="end_date", label="To"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
