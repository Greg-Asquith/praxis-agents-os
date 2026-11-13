# apps/api/integrations/google_ads/tools/update_asset_groups.py

"""Approval-only tool that changes live Performance Max asset groups in ordered atomic requests."""

import asyncio
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import RunContext, ToolReturn

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
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
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.asset_group_state import (
    URL_OPTION_PATHS,
    LiveAssetGroup,
    LiveAssetGroups,
    LiveAudience,
    read_asset_groups,
    segment_key,
)
from ..operations.build import CampaignBuild, dry_run_build, send_build
from ..operations.campaign_settings import api_value
from ..operations.edits import STALE_MESSAGE
from ..operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
    joined_ledger,
    thaw_fields,
)
from ..operations.performance_max import audience_segment, text_asset
from .schemas.asset_group_updates import (
    MAX_ASSET_GROUP_UPDATES,
    GoogleAdsAssetGroupUpdate,
    GoogleAdsUpdateAssetGroupsOutput,
    GoogleAdsUpdateAssetGroupsRequest,
)
from .schemas.performance_max import (
    ASSET_GROUP_LIMITS,
    MAX_AUDIENCE_SEGMENTS,
    MAX_SEARCH_THEMES,
    SHORT_DESCRIPTION,
)
from .utils.accounts import NOT_SHOWN, approval_accounts, writable_entries
from .utils.ad_group_builds import MAX_AUDIT_ITEM_CHARS
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.performance_max_builds import (
    MEDIA_FROM_ANOTHER_ACCOUNT,
    audience_id,
    read_images,
    read_signal_audiences,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_asset_groups"
_FAMILY = "asset_groups"
_IDENTITY = ("step",)
# One row per change, with room for long text.
_MAX_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_OUTCOMES = 50

_TEXT_KINDS = ("HEADLINE", "LONG_HEADLINE", "DESCRIPTION")
_IMAGE_KINDS = ("MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE")
_LINK_KINDS = (*_TEXT_KINDS, *_IMAGE_KINDS, "YOUTUBE_VIDEO")
# Each setting's field in Google's JSON names, in the order an update masks them.
_SETTING_PATHS: Mapping[str, str] = {"name": "name", "final_url": "finalUrls", **URL_OPTION_PATHS}
# Each kind's minimum and maximum in one asset group.
_LIMITS: Mapping[str, tuple[int, int]] = {
    **ASSET_GROUP_LIMITS,
    "search_theme": (0, MAX_SEARCH_THEMES),
    "audience_signal": (0, MAX_AUDIENCE_SEGMENTS),
}
_NOUNS = {
    "HEADLINE": "headline",
    "LONG_HEADLINE": "long headline",
    "DESCRIPTION": "description",
    "MARKETING_IMAGE": "landscape image",
    "SQUARE_MARKETING_IMAGE": "square image",
    "PORTRAIT_MARKETING_IMAGE": "portrait image",
    "YOUTUBE_VIDEO": "video",
    "search_theme": "search theme",
    "audience_signal": "audience in its signal",
}
_APPLIED = {"add": "added", "remove": "removed", "set": "changed"}

_MISSING = "This asset group is removed, or no longer exists in Google Ads."
_CAMPAIGN_REMOVED = "This asset group's campaign is removed."
_NOT_PERFORMANCE_MAX = "Only asset groups in Performance Max campaigns can change here."
_SEVERAL_AUDIENCES = (
    "This asset group has more than one audience signal. Change them in Google Ads."
)
_UNREAD_AUDIENCE = "Google Ads didn't return this asset group's audience signal. Check again."
_SHARED_AUDIENCE = (
    "This asset group's audience signal is a saved audience other asset groups can use. "
    "Change it in Google Ads."
)
_UNKNOWN_AUDIENCE = "The account doesn't have this audience."
_UNKNOWN_IMAGE = "This isn't an image in the account."
_IMAGE_MISFIT = "This image doesn't fit as a {noun}."
_TOO_FEW = "Every asset group needs at least {minimum} {noun}; this would leave {after}."
_TOO_MANY = "An asset group takes at most {maximum} of these; this would make {after}."
_NO_SHORT_DESCRIPTION = (
    f"Every asset group needs one description of {SHORT_DESCRIPTION} characters or fewer."
)
_NOTHING_TO_SEND = "Everything here is already in place in Google Ads."
_NOT_SENT = "This wasn't sent, because an earlier part of the change didn't go through."

type _Action = Literal["add", "remove", "set"]
type _State = Literal["change", "already_set", "not_found"]


@dataclass(frozen=True, slots=True)
class _Row:
    """One change to one asset group, with what's live and why it can't happen."""

    group: str
    action: _Action
    kind: str
    # The text, URL, name, asset ID, theme, or `kind:key` audience the change is about; a URL
    # option as the card shows it, empty when it's cleared.
    value: str
    # What the card and result call it, such as an image's name.
    item: str
    state: _State = "change"
    # The live link, signal, name, or URL the change was checked against.
    before: str | None = None
    problem: str | None = None
    # A URL option in card terms, which is what Google is sent and compared with.
    option: Any = None

    @property
    def row(self) -> str:
        """Names the change within its group, as the card does."""
        return self.kind if self.action == "set" else f"{self.kind}|{self.value}"

    @property
    def source(self) -> str:
        """Names the build steps this change sends; one step can carry several changes."""
        if self.action == "set":
            return f"{self.group}|settings"
        if self.kind == "audience_signal":
            return f"{self.group}|audience"
        return f"{self.group}|{self.action}|{self.row}"

    @property
    def changes(self) -> bool:
        return self.state == "change" and self.problem is None


@dataclass(frozen=True, slots=True)
class _Known:
    """The added images and audiences the account has, read before approval."""

    images: Mapping[str, Mapping[str, Any]]
    audiences: Mapping[str, str]


def _requested(update: GoogleAdsAssetGroupUpdate) -> list[_Row]:
    """Every change the entry asks for, with removals before additions, against nothing read."""
    group = update.asset_group.resource_name
    rows: list[_Row] = []
    if update.name is not None:
        rows.append(_Row(group, "set", "name", update.name, update.name))
    if update.final_url is not None:
        rows.append(_Row(group, "set", "final_url", update.final_url, update.final_url))
    for setting, option in (update.url_options.requested if update.url_options else {}).items():
        text = _option_text(option)
        rows.append(_Row(group, "set", setting, text, text, option=option))
    for action, assets in (("remove", update.remove_assets), ("add", update.add_assets)):
        labels = {image.asset.asset_id: image.asset for image in assets.images}
        labels.update({video.asset_id: video for video in assets.videos})
        for kind, value in assets.items:
            reference = labels.get(value) if kind not in _TEXT_KINDS else None
            other_account = (
                reference is not None and reference.customer_id != update.asset_group.customer_id
            )
            rows.append(
                _Row(
                    group,
                    action,
                    kind,
                    value,
                    (reference.label if reference else None) or value,
                    problem=MEDIA_FROM_ANOTHER_ACCOUNT if other_account else None,
                )
            )
    for action, themes in (
        ("remove", update.remove_search_themes),
        ("add", update.add_search_themes),
    ):
        rows.extend(_Row(group, action, "search_theme", theme, theme) for theme in themes)
    for action, audiences in (
        ("remove", update.remove_audience_signals),
        ("add", update.add_audience_signals),
    ):
        rows.extend(
            _Row(
                group,
                action,
                "audience_signal",
                audience_id(item.kind, item.key),
                item.name or item.key,
            )
            for item in audiences
        )
    return rows


def _option_text(option: Any) -> str:
    """Shows a URL option as the card does: its text, or custom parameters as `key=value`."""
    if isinstance(option, list):
        return ", ".join(f"{item['key']}={item['value']}" for item in option)
    return option or ""


def _group_problem(group: LiveAssetGroup | None) -> str | None:
    if group is None or group.status == "REMOVED":
        return _MISSING
    if group.campaign_status == "REMOVED":
        return _CAMPAIGN_REMOVED
    if group.channel != "PERFORMANCE_MAX":
        return _NOT_PERFORMANCE_MAX
    return None


def _audience(
    group: LiveAssetGroup, live: LiveAssetGroups
) -> tuple[LiveAudience | None, str | None]:
    """The group's own audience signal, or why its signal can't change here."""
    if not group.audience_signals:
        return None, None
    if len(group.audience_signals) > 1:
        return None, _SEVERAL_AUDIENCES
    audience = live.audiences.get(group.audience_signals[0][1])
    if audience is None:
        return None, _UNREAD_AUDIENCE
    if audience.scope != "ASSET_GROUP":
        return audience, _SHARED_AUDIENCE
    return audience, None


def _settle(row: _Row, group: LiveAssetGroup, audience: LiveAudience | None) -> _Row:
    """Fills what's live for the change: the link or signal it finds, or the value it replaces."""
    if row.kind == "name":
        return replace(row, before=group.name, state=_set_state(group.name == row.value))
    if row.kind == "final_url":
        now = group.final_urls[0] if group.final_urls else None
        return replace(row, before=now, state=_set_state(group.final_urls == (row.value,)))
    if row.kind in URL_OPTION_PATHS:
        live = group.url_options.get(row.kind)
        return replace(row, before=_option_text(live) or None, state=_set_state(live == row.option))
    found: str | None = None
    if row.kind in _LINK_KINDS:
        found = next(
            (
                link.resource_name
                for link in group.links
                if link.field_type == row.kind
                and (link.text if row.kind in _TEXT_KINDS else link.asset_id) == row.value
            ),
            None,
        )
    elif row.kind == "search_theme":
        theme = row.value.casefold()
        found = next((name for name, text in group.themes if text.casefold() == theme), None)
    elif audience is not None and row.value in {audience_id(*key) for key in audience.segments}:
        found = group.audience_signals[0][0]
    if row.action == "add":
        return replace(row, before=found, state="already_set" if found else "change")
    return replace(row, before=found, state="change" if found else "not_found")


def _set_state(same: bool) -> _State:
    return "already_set" if same else "change"


def _known_problem(row: _Row, known: _Known | None) -> str | None:
    """Why the account can't take an added image or audience; None when nothing was read."""
    if known is None or row.action != "add" or row.state != "change":
        return None
    if row.kind in _IMAGE_KINDS:
        image = known.images.get(row.value)
        if image is None:
            return _UNKNOWN_IMAGE
        if row.kind not in image.get("fits", ()):
            return _IMAGE_MISFIT.format(noun=_NOUNS[row.kind])
    if row.kind == "audience_signal" and row.value not in known.audiences:
        return _UNKNOWN_AUDIENCE
    return None


def _within_limits(rows: Sequence[_Row], group: LiveAssetGroup, segments: int) -> list[_Row]:
    """Refuses additions over a maximum and removals under a minimum, naming the count after."""
    counts = Counter(link.field_type for link in group.links if link.advertiser)
    counts["search_theme"] = len(group.themes)
    counts["audience_signal"] = segments
    descriptions = {link.text for link in group.links if link.field_type == "DESCRIPTION"}
    automatic = _automatic(group)
    for row in rows:
        if row.changes and row.action != "set" and row.before not in automatic:
            counts[row.kind] += 1 if row.action == "add" else -1
            if row.kind == "DESCRIPTION" and row.action == "add":
                descriptions.add(row.value)
            elif row.kind == "DESCRIPTION":
                descriptions.discard(row.value)
    # A retail group with no assets of its own takes Google's assets from the feed.
    exempt = group.retail and not any(counts[kind] for kind in _LINK_KINDS)
    no_short = bool(descriptions) and all(
        len(text or "") > SHORT_DESCRIPTION for text in descriptions
    )
    return [
        replace(row, problem=problem)
        if row.changes
        and row.action != "set"
        and row.before not in automatic
        and (problem := _limit_problem(row, counts[row.kind], exempt=exempt, no_short=no_short))
        else row
        for row in rows
    ]


def _automatic(group: LiveAssetGroup) -> set[str]:
    """The links Google made itself, which its minimums and maximums don't count."""
    return {link.resource_name for link in group.links if not link.advertiser}


def _limit_problem(row: _Row, after: int, *, exempt: bool, no_short: bool) -> str | None:
    minimum, maximum = _LIMITS[row.kind]
    if row.action == "add":
        return _TOO_MANY.format(maximum=maximum, after=after) if after > maximum else None
    if exempt:
        return None
    if after < minimum:
        noun = _NOUNS[row.kind] + ("s" if minimum > 1 else "")
        return _TOO_FEW.format(minimum=minimum, noun=noun, after=after)
    if row.kind == "DESCRIPTION" and no_short and len(row.value) <= SHORT_DESCRIPTION:
        return _NO_SHORT_DESCRIPTION
    return None


def _plan(
    update: GoogleAdsAssetGroupUpdate, live: LiveAssetGroups, known: _Known | None
) -> tuple[list[_Row], str | None]:
    """Plans one entry against what's live, with the problem that stops the whole group."""
    rows = _requested(update)
    group = live.groups.get(update.asset_group.resource_name)
    problem = _group_problem(group)
    if group is None or problem:
        return [replace(row, problem=problem) for row in rows], problem
    audience, audience_problem = _audience(group, live)
    planned = []
    for row in rows:
        settled = _settle(row, group, audience)
        reason = settled.problem or _known_problem(settled, known)
        if row.kind == "audience_signal" and audience_problem:
            reason = audience_problem
        planned.append(replace(settled, problem=reason))
    segments = len(audience.segments) if audience else 0
    return _within_limits(planned, group, segments), None


def _parts(group: LiveAssetGroup, rows: Sequence[_Row]) -> dict[str, int]:
    """Puts each link and theme change in the earliest request that keeps every type in limits.

    Google checks an asset group's minimums and maximums against the group as each request
    finds it, not against where the request leaves it. So a request takes at most the
    removals that keep a type at its minimum and the additions that keep it at its maximum.
    """
    counts = Counter(link.field_type for link in group.links if link.advertiser)
    counts["search_theme"] = len(group.themes)
    parts: dict[str, int] = {}
    automatic = _automatic(group)
    for kind in (*_LINK_KINDS, "search_theme"):
        # Removing a link Google made changes no count, so it goes in the first request.
        changing = [
            row for row in rows if row.kind == kind and row.changes and row.before not in automatic
        ]
        removes = [row for row in changing if row.action == "remove"]
        adds = [row for row in changing if row.action == "add"]
        minimum, maximum = _LIMITS[kind]
        # A retail group may hold no assets of its own, as Google fills it from the feed.
        minimum = 0 if group.retail else minimum
        current, part = counts[kind], 0
        while removes or adds:
            taken = max(current - minimum, 0)
            room = max(maximum - current, 0)
            batch = (removes[:taken], adds[:room]) if taken or room else (removes, adds)
            for row in (*batch[0], *batch[1]):
                parts[row.source] = part
            removes, adds = removes[len(batch[0]) :], adds[len(batch[1]) :]
            current += len(batch[1]) - len(batch[0])
            part += 1
    return parts


def _compile(
    build: CampaignBuild,
    group: LiveAssetGroup,
    rows: Sequence[_Row],
    live: LiveAssetGroups,
    parts: Mapping[str, int] | None = None,
    part: int = 0,
) -> None:
    """Adds one group's changes in one request: settings, links, themes, and signal.

    Args:
        parts: Which request each change goes in, from `_parts`; every change when None.
            Settings and the audience signal always go in the first.
    """
    changing = [
        row for row in rows if row.changes and (parts is None or parts.get(row.source, 0) == part)
    ]
    settings = {row.kind: row for row in changing if row.action == "set"}
    if settings:
        body: dict[str, Any] = {"resourceName": group.resource_name}
        for kind, path in _SETTING_PATHS.items():
            if kind not in settings:
                continue
            row = settings[kind]
            if kind in URL_OPTION_PATHS:
                # A null value in the mask clears the option.
                body[path] = api_value(kind, row.option)
            else:
                body[path] = [row.value] if kind == "final_url" else row.value
        build.update(
            "assetGroup",
            body,
            update_mask=",".join(path for path in _SETTING_PATHS.values() if path in body),
            label=f"{group.name}: settings",
            source=f"{group.resource_name}|settings",
        )
    for row in changing:
        if row.action == "remove" and row.kind != "audience_signal" and row.before:
            resource = "assetGroupSignal" if row.kind == "search_theme" else "assetGroupAsset"
            build.remove(resource, row.before, label=row.item, source=row.source)
        elif row.action == "add" and row.kind == "search_theme":
            build.create(
                "assetGroupSignal",
                {"assetGroup": group.resource_name, "searchTheme": {"text": row.value}},
                label=row.item,
                source=row.source,
            )
        elif row.action == "add" and row.kind in _LINK_KINDS:
            asset = (
                text_asset(build, row.value, row.source)
                if row.kind in _TEXT_KINDS
                else f"customers/{build.customer_id}/assets/{row.value}"
            )
            build.create(
                "assetGroupAsset",
                {"assetGroup": group.resource_name, "asset": asset, "fieldType": row.kind},
                label=row.item,
                source=row.source,
            )
    audience_rows = [row for row in changing if row.kind == "audience_signal"]
    if audience_rows:
        _compile_audience(build, group, audience_rows, _audience(group, live)[0])


def _compile_audience(
    build: CampaignBuild,
    group: LiveAssetGroup,
    rows: Sequence[_Row],
    audience: LiveAudience | None,
) -> None:
    """Rewrites the segments of the group's own audience, or makes one when it has none."""
    source = rows[0].source
    label = f"{group.name}: audience signal"
    removed = {row.value for row in rows if row.action == "remove"}
    added = [
        audience_segment(build.customer_id, *row.value.split(":", 1))
        for row in rows
        if row.action == "add"
    ]
    if audience is None:
        name = build.create(
            "audience",
            {
                "scope": "ASSET_GROUP",
                "assetGroup": group.resource_name,
                "dimensions": [{"audienceSegments": {"segments": added}}],
            },
            label=label,
            source=source,
        )
        build.create(
            "assetGroupSignal",
            {"assetGroup": group.resource_name, "audience": {"audience": name}},
            label=label,
            source=source,
        )
        return
    others: list[Mapping[str, Any]] = []
    segments: list[Mapping[str, Any]] = []
    for dimension in audience.dimensions:
        if "audienceSegments" not in dimension:
            others.append(dimension)
            continue
        for segment in dimension["audienceSegments"].get("segments") or ():
            key = segment_key(segment)
            if key is None or audience_id(*key) not in removed:
                segments.append(segment)
    segments.extend(added)
    if not segments and not others:
        # An audience needs a dimension, so the group stops signalling one instead.
        build.remove("assetGroupSignal", group.audience_signals[0][0], label=label, source=source)
        return
    dimensions = [*others, *([{"audienceSegments": {"segments": segments}}] if segments else [])]
    build.update(
        "audience",
        {"resourceName": audience.resource_name, "dimensions": dimensions},
        update_mask="dimensions",
        label=label,
        source=source,
    )


def _split(
    request: GoogleAdsUpdateAssetGroupsRequest,
) -> dict[str, list[GoogleAdsAssetGroupUpdate]]:
    by_account: dict[str, list[GoogleAdsAssetGroupUpdate]] = {}
    for entry in request.entries:
        by_account.setdefault(entry.asset_group.customer_id, []).append(entry)
    return by_account


def _account_builds(
    customer_id: str, live: LiveAssetGroups, planned: Mapping[str, Sequence[_Row]]
) -> list[CampaignBuild]:
    """Returns the account's requests in the order they're sent; empty ones are left out."""
    parts = {key: _parts(live.groups[key], rows) for key, rows in planned.items()}
    count = 1 + max((part for found in parts.values() for part in found.values()), default=0)
    builds = []
    for part in range(count):
        build = CampaignBuild(customer_id)
        for key, rows in planned.items():
            _compile(build, live.groups[key], rows, live, parts[key], part)
        if build.steps:
            builds.append(build)
    return builds


async def _read(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    updates: Sequence[GoogleAdsAssetGroupUpdate],
) -> LiveAssetGroups:
    return await read_asset_groups(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        asset_group_ids=[update.asset_group.asset_group_id for update in updates],
    )


async def google_ads_update_asset_groups(
    ctx: RunContext[RuntimeDeps],
    entries: Annotated[
        list[GoogleAdsAssetGroupUpdate],
        Field(
            min_length=1,
            max_length=MAX_ASSET_GROUP_UPDATES,
            description="One entry per asset group, with only what changes in it.",
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    request = validated_request(GoogleAdsUpdateAssetGroupsRequest, {"entries": entries})
    display = approved_display_args(ctx)
    shown = display.get("_checks") if isinstance(display.get("_checks"), Mapping) else {}
    by_account = _split(request)

    async def operation(entry: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        updates = by_account[entry.external_id]
        client: GoogleAdsClient | None = None
        builds: list[CampaignBuild] = []
        planned: dict[str, list[_Row]] = {}
        names: dict[str, tuple[str, str]] = {}
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending, builds
            client = await google_ads_client(ctx, entry)
            live = await _read(client, entry, updates)
            for update in updates:
                key = update.asset_group.resource_name
                rows, problem = _plan(update, live, None)
                refusal = problem or _unapproved(rows, shown.get(key))
                label = update.asset_group.label or update.asset_group.asset_group_id
                if refusal:
                    raise IntegrationValidationError(
                        f"{label}: {refusal}",
                        provider_key="google_ads",
                        failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
                    )
                group = live.groups[key]
                planned[key] = rows
                names[key] = (group.name, group.campaign_name)
            builds = _account_builds(entry.external_id, live, planned)
            if not builds:
                raise IntegrationValidationError(
                    _NOTHING_TO_SEND,
                    provider_key="google_ads",
                    failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
                )
            pending = _pending_detail(entry, builds, names)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None:
                raise RuntimeError("Google Ads asset group update preparation did not complete")
            try:
                ledger = await _send_in_order(client, entry, builds)
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, ledger, identity_keys=_IDENTITY)
            data = _result(entry, planned, names, builds, ledger)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                data,
                status=status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=data if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_asset_groups",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[update.asset_group for update in request.entries],
        operation=operation,
    )
    return split_fan_out_tool_return(results)


def _unapproved(rows: Sequence[_Row], check: Any) -> str | None:
    """Why the group's changes can't be sent: not what the approver saw, or a problem shown."""
    if not isinstance(check, Mapping) or check.get("unavailable") is not False:
        return NOT_SHOWN
    if isinstance(check.get("problem"), str):
        return check["problem"]
    shown = {
        (row.get("row"), row.get("action")): row
        for row in check.get("rows") or ()
        if isinstance(row, Mapping)
    }
    for row in rows:
        seen = shown.get((row.row, row.action))
        if seen is None:
            return NOT_SHOWN
        if seen.get("state") != row.state or seen.get("before") != row.before:
            return STALE_MESSAGE
        if isinstance(seen.get("problem"), str):
            return seen["problem"]
        # A problem the approver never saw means the group changed since.
        if row.problem is not None:
            return STALE_MESSAGE
    return None


async def _send_in_order(
    client: GoogleAdsClient, entry: ResolvedContextEntry, builds: Sequence[CampaignBuild]
) -> GoogleAdsMutationLedger:
    """Sends each request once the one before it fully applied; the rest are recorded unsent.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute holding every request's outcome.
    """
    ledgers: list[GoogleAdsMutationLedger] = []
    for part, build in enumerate(builds):
        if ledgers and any(effect.outcome != "applied" for effect in ledgers[-1].effects):
            ledgers.extend(
                _unsent(later, number) for number, later in enumerate(builds) if number >= part
            )
            break
        try:
            built = await send_build(
                client,
                build,
                login_customer_id=login_customer_id(entry),
                family=_FAMILY,
                operation=_OPERATION,
            )
        except asyncio.CancelledError as exc:
            sent = _numbered(exc.ledger, part)  # type: ignore[attr-defined]
            unsent = [
                _unsent(later, number) for number, later in enumerate(builds) if number > part
            ]
            exc.ledger = joined_ledger([*ledgers, sent, *unsent], family=_FAMILY)  # type: ignore[attr-defined]
            raise
        ledgers.append(_numbered(built.ledger, part))
    return joined_ledger(ledgers, family=_FAMILY)


def _step_id(part: int, index: int) -> str:
    return f"{part}.{index}"


def _numbered(ledger: GoogleAdsMutationLedger, part: int) -> GoogleAdsMutationLedger:
    """Names each step by its request and place, as the audit intents do."""

    def renamed(fields: Any) -> Any:
        values = thaw_fields(fields)
        return freeze_fields({**values, "step": _step_id(part, int(values["step"]))})

    parents = tuple(
        replace(
            parent,
            identity=renamed(parent.identity),
            effects=tuple(
                replace(effect, fields=renamed(effect.fields)) for effect in parent.effects
            ),
        )
        for parent in ledger.parents
    )
    return replace(ledger, parents=parents)


def _unsent(build: CampaignBuild, part: int) -> GoogleAdsMutationLedger:
    fields = [
        {
            "step": _step_id(part, index),
            "resource": step.resource,
            "label": step.label or step.resource,
        }
        for index, step in enumerate(build.steps)
    ]
    return build_mutation_ledger(
        family=_FAMILY,
        action="create",
        parent_fields=fields,
        skipped_indices={},
        submitted=list(enumerate(fields)),
        outcomes=[("failed", None, "NOT_SENT", _NOT_SENT)] * len(fields),
        projection=GoogleAdsMutationProjection(
            applied_key="created", skipped_key="skipped", errors_key="errors"
        ),
    )


def _pending_detail(
    entry: ResolvedContextEntry,
    builds: Sequence[CampaignBuild],
    names: Mapping[str, tuple[str, str]],
) -> PendingIntegrationOperationDetail:
    # One group per asset group, so its name is stored once rather than on every change.
    items: dict[str, list[IntegrationOperationIntent]] = defaultdict(list)
    for part, build in enumerate(builds):
        for index, step in enumerate(build.steps):
            items[str(step.source).split("|", 1)[0]].append(
                IntegrationOperationIntent(
                    fields={
                        "step": _step_id(part, index),
                        "kind": step.resource,
                        "item": step.label[:MAX_AUDIT_ITEM_CHARS],
                    }
                )
            )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=group,
                action="update",
                entity_type="google_ads_asset_group",
                display_name=names[group][0],
                items=intents,
            )
            for group, intents in items.items()
        ],
    )


def _step_outcomes(
    builds: Sequence[CampaignBuild], ledger: GoogleAdsMutationLedger
) -> dict[str, Any]:
    """Each source's worst effect: a failure, then an unclear reply, then success."""
    rank = {"applied": 0, "unverified": 1, "failed": 2}
    steps = [step for build in builds for step in build.steps]
    worst: dict[str, Any] = {}
    for step, parent in zip(steps, ledger.parents, strict=True):
        effect = parent.effects[0]
        current = worst.get(step.source)
        if current is None or rank[effect.outcome] > rank[current.outcome]:
            worst[step.source] = effect
    return worst


def _result(
    entry: ResolvedContextEntry,
    planned: Mapping[str, Sequence[_Row]],
    names: Mapping[str, tuple[str, str]],
    builds: Sequence[CampaignBuild],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    """Returns every row for the card, and the counts with what didn't happen for the agent."""
    effects = _step_outcomes(builds, ledger)
    outcomes = []
    for group, rows in planned.items():
        for row in rows:
            effect = effects.get(row.source) if row.state == "change" else None
            if row.state != "change":
                outcome = row.state
            elif effect is None or effect.outcome == "unverified":
                outcome = "unverified"
            else:
                outcome = _APPLIED[row.action] if effect.outcome == "applied" else "failed"
            outcomes.append(
                {
                    "asset_group_name": names[group][0],
                    "campaign_name": names[group][1] or None,
                    "action": row.action,
                    "kind": row.kind,
                    "item": row.item,
                    "before": row.before if row.action == "set" else None,
                    "outcome": outcome,
                    "error_code": effect.error_code if effect else None,
                    "message": effect.message if effect else None,
                }
            )
    counts = Counter(row["outcome"] for row in outcomes)
    totals = {
        key: counts.get(key, 0)
        for key in (*_APPLIED.values(), "already_set", "not_found", "failed", "unverified")
    }
    missed = [row for row in outcomes if row["outcome"] in {"failed", "unverified"}]
    base = {"account_id": entry.external_id, "counts": totals}
    return {
        "display_result": {**base, "outcomes": outcomes, "outcomes_truncated": False},
        "model_result": {
            **base,
            "outcomes": missed[:_MAX_MODEL_OUTCOMES],
            "outcomes_truncated": len(missed) > _MAX_MODEL_OUTCOMES,
        },
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts, and per asset group what's live, the problems, and Google's dry run."""
    request = GoogleAdsUpdateAssetGroupsRequest.model_validate(args)
    entries = writable_entries(deps.active_context)
    by_account = _split(request)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, updates in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), updates))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    updates: Sequence[GoogleAdsAssetGroupUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account and dry runs its changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await _read(client, entry, updates)
        known = await _read_known(client, entry, updates)
        planned = {
            update.asset_group.resource_name: _plan(update, live, known) for update in updates
        }
        google = await _dry_run(client, entry, planned, live)
    except (IntegrationError, LookupError):
        return {update.asset_group.resource_name: {"unavailable": True} for update in updates}
    checks = {}
    for update in updates:
        key = update.asset_group.resource_name
        rows, problem = planned[key]
        checks[key] = _group_check(update, live, rows, problem, google)
    return checks


async def _read_known(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    updates: Sequence[GoogleAdsAssetGroupUpdate],
) -> _Known:
    images = sorted(
        {image.asset.asset_id for update in updates for image in update.add_assets.images}
    )
    return _Known(
        images=await read_images(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            asset_ids=images,
        ),
        audiences=await read_signal_audiences(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            audiences=[item for update in updates for item in update.add_audience_signals],
        ),
    )


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    planned: Mapping[str, tuple[list[_Row], str | None]],
    live: LiveAssetGroups,
) -> dict[str, str]:
    """Returns Google's reason for each change it would reject, by build source.

    Only the first request can be checked whole, since later ones rely on it applying; their
    new text is checked on its own. Google refuses partial failure for asset group changes,
    so it names only its first rejection. One for the whole request applies to all of it.
    """
    ready = {key: rows for key, (rows, problem) in planned.items() if problem is None}
    builds = _account_builds(entry.external_id, live, ready)
    if not builds:
        return {}
    texts = CampaignBuild(entry.external_id)
    for step in (step for build in builds[1:] for step in build.steps):
        if step.resource == "asset":
            body = {key: value for key, value in step.body.items() if key != "resourceName"}
            texts.create("asset", body, label=step.label, source=step.source)
    problems: dict[str, str] = {}
    for build in (builds[0], texts):
        if not build.steps:
            continue
        for problem in await dry_run_build(
            client,
            build,
            login_customer_id=login_customer_id(entry),
            operation=_OPERATION,
            partial_failure=False,
        ):
            steps = [problem.step] if problem.step else build.steps
            for step in steps:
                problems.setdefault(str(step.source), f"Google says: {problem.message}")
    return problems


def _group_check(
    update: GoogleAdsAssetGroupUpdate,
    live: LiveAssetGroups,
    rows: Sequence[_Row],
    problem: str | None,
    google: Mapping[str, str],
) -> dict[str, Any]:
    """Builds the card's view of one asset group, and the live state approval plans against."""
    group = live.groups.get(update.asset_group.resource_name)
    now: Counter[str] = Counter()
    if group is not None:
        now.update(link.field_type for link in group.links if link.advertiser)
        now["search_theme"] = len(group.themes)
        audience = _audience(group, live)[0]
        now["audience_signal"] = len(audience.segments) if audience else 0
    return {
        "unavailable": False,
        "name": group.name if group else update.asset_group.label,
        "campaign_name": group.campaign_name if group else None,
        "retail": bool(group and group.retail),
        "url_options": dict(group.url_options) if group else {},
        "problem": problem,
        "now": dict(now),
        "rows": [
            {
                "row": row.row,
                "action": row.action,
                "kind": row.kind,
                "item": row.item,
                "before": row.before,
                "state": row.state,
                "problem": row.problem or (google.get(row.source) if row.changes else None),
            }
            for row in rows
        ],
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_asset_groups",
    function=google_ads_update_asset_groups,
    description=(
        "Change up to 100 live Performance Max asset groups in one approval. Each entry names "
        "one asset_group and only what changes: name; final_url; url_options (final_url_suffix, "
        "tracking_template, and up to 8 custom_parameters [{key, value}], each replacing the "
        "group's value, with an empty value or list clearing it); add_assets and remove_assets "
        "({headlines (30 characters), long_headlines (90), descriptions (90), images [{asset, "
        "field_type}], videos}); add_search_themes and remove_search_themes (80 characters); "
        "and add_audience_signals and remove_audience_signals [{kind, key, name}] (user_list, "
        "user_interest, or custom_audience from google_ads_search_targeting). Text is removed "
        "by its exact text; images and videos by their asset, images also by field_type. To "
        "swap a headline, add the new one and remove the old one in the same entry. Images and "
        "videos come from google_ads_upload_media. An asset group needs 3 headlines, 1 long "
        "headline, 2 descriptions (one of 60 characters or fewer), 1 landscape and 1 square "
        "image, and takes at most 15 headlines, 5 long headlines, 5 descriptions, 25 search "
        "themes, and 20 audiences in its signal; a change that breaks a limit is refused. "
        "Search themes and audience signals guide Google without limiting reach. A group's "
        "audience signal that is a saved audience shared with other groups can't change here. "
        "Changes go in the fewest requests that keep every group within those limits as each "
        "request runs, so a full replacement may take two or three; if one fails, later ones "
        "aren't sent. "
        "Status and removal use google_ads_update_status and google_ads_remove_objects."
    ),
    provider="google_ads",
    label="Update Google Ads Asset Groups",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=GoogleAdsUpdateAssetGroupsOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateAssetGroupsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("entries",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Asset Groups",
        completed_label="Updated Asset Groups",
        failed_label="Couldn't Update Asset Groups",
        approval_title="Change Asset Groups",
        approval_prompt="The agent wants to change these Performance Max asset groups.",
        approve_label="Apply Changes",
        arg_fields=(
            ToolFieldPresentation(
                key="entries",
                label="Asset Groups",
                editable=True,
                format="structured",
                # The first kind authorises a review; the others are what entries add.
                entity_kinds=("google_ads_asset_group", "google_ads_asset", "google_ads_audience"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
