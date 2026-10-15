// apps/web/src/integrations/meta_ads/components/ad-editor.tsx

import { ChevronLeftIcon, ChevronRightIcon, ImageUpIcon, PlusIcon, XIcon } from "lucide-react"
import { useId, useState } from "react"

import { fieldLabelClass } from "@/components/tool-ui/field-styles"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { AdPreview, PostAdPreview } from "@/integrations/meta_ads/components/ad-preview"
import { AdSetPicker } from "@/integrations/meta_ads/components/ad-set-picker"
import { ButtonSelect } from "@/integrations/meta_ads/components/button-select"
import { CarouselCards } from "@/integrations/meta_ads/components/carousel-cards"
import { EditorField, LabelledInput } from "@/integrations/meta_ads/components/editor-fields"
import {
  CheckMark,
  CheckMessages,
  LengthCounter,
} from "@/integrations/meta_ads/components/field-notes"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import { MediaPicker } from "@/integrations/meta_ads/components/media-picker"
import {
  adSetName,
  FORMAT_LABELS,
  RECOMMENDED_LENGTHS,
  type CreateAdsArgs,
  type PostPreview,
} from "@/integrations/meta_ads/lib/create-ads-args"
import {
  checksFor,
  hasError,
  type AdRow,
  type CheckField,
} from "@/integrations/meta_ads/lib/create-ads-checks"
import {
  blankToNull,
  editAd,
  followsShared,
  setAdMedia,
  setAdSets,
  type EditableAdKey,
  type EditedAds,
} from "@/integrations/meta_ads/lib/create-ads-edits"
import { titleCaseToken, urlDomain } from "@/lib/format"

type SettingKey = "link" | "call_to_action" | "url_tags"
type Edits = {
  args: CreateAdsArgs
  disabled: boolean
  id: string
  onEdit: (ads: EditedAds) => void
  onEditSetting: (key: SettingKey, value: string | null) => void
  row: AdRow
}

/** One ad in one column: its text and settings on Edit, and how it looks on Preview. */
export function AdEditor({
  args,
  count,
  row,
  disabled,
  onEdit,
  onEditSetting,
  onSelect,
}: {
  args: CreateAdsArgs
  count: number
  row: AdRow
  disabled: boolean
  onEdit: (ads: EditedAds) => void
  onEditSetting: (key: SettingKey, value: string | null) => void
  onSelect: (index: number) => void
}) {
  const id = useId()
  const [tab, setTab] = useState<"edit" | "preview">("edit")
  const { ad } = row
  const edits: Edits = { args, disabled, id, onEdit, onEditSetting, row }
  const adSets = ad.adSetIds.map((adSetId) => adSetName(args, adSetId))
  const kind = ad.post
    ? `${ad.post.source === "facebook" ? "Facebook" : "Instagram"} post`
    : `${FORMAT_LABELS[ad.format]} ad${ad.format === "carousel" ? ` with ${String(ad.cards.length)} cards` : ""}`
  return (
    <div className="@container grid min-w-0 gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {count > 1 ? (
          <div className="flex items-center gap-1">
            <Button
              aria-label="Previous ad"
              disabled={ad.index === 0}
              onClick={() => {
                onSelect(ad.index - 1)
              }}
              size="icon"
              type="button"
              variant="outline"
            >
              <ChevronLeftIcon />
            </Button>
            <p className="px-1 text-sm font-medium tabular-nums">
              Ad {String(ad.index + 1)} of {String(count)}
            </p>
            <Button
              aria-label="Next ad"
              disabled={ad.index === count - 1}
              onClick={() => {
                onSelect(ad.index + 1)
              }}
              size="icon"
              type="button"
              variant="outline"
            >
              <ChevronRightIcon />
            </Button>
          </div>
        ) : null}
        <CheckMark check={row.check} checks={row.checks} />
        {ad.post ? null : (
          <Tabs
            className="ml-auto"
            onValueChange={(value) => {
              setTab(value === "preview" ? "preview" : "edit")
            }}
            value={tab}
          >
            <TabsList aria-label={`Edit or preview ${ad.name}`}>
              <TabsTrigger value="edit">Edit</TabsTrigger>
              <TabsTrigger value="preview">Preview</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
      </div>
      <p className="text-muted-foreground text-sm wrap-anywhere">
        {kind} · {adSets.join(", ")}
      </p>
      {ad.post ? (
        <PostAdBody {...edits} post={ad.post} />
      ) : tab === "preview" ? (
        <PreviewPanel {...edits} />
      ) : (
        <EditPanel {...edits} />
      )}
    </div>
  )
}

function EditPanel({ args, disabled, id, onEdit, onEditSetting, row }: Edits) {
  const { ad } = row
  const edit = (key: EditableAdKey, value: string | null) => {
    onEdit(editAd(args, ad.index, key, value))
  }
  const carousel = ad.format === "carousel"
  const shownFields = new Set<CheckField>([
    "name",
    "primary_text",
    "link",
    "call_to_action",
    "url_tags",
    "media",
    ...(carousel ? (["cards"] as const) : (["headline", "description"] as const)),
  ])
  // A check for a field this format doesn't show still needs to be seen.
  const unplaced = row.checks.filter((check) => !shownFields.has(check.field))
  return (
    <div className="grid min-w-0 gap-4">
      <CheckMessages checks={unplaced} />
      <NameAndAdSet args={args} disabled={disabled} id={id} onEdit={onEdit} row={row} />
      {carousel ? null : <MediaRow args={args} disabled={disabled} onEdit={onEdit} row={row} />}
      <EditorField
        checks={checksFor(row, "primary_text")}
        counter={
          <LengthCounter length={ad.primaryText.length} limit={RECOMMENDED_LENGTHS.primaryText} />
        }
        id={`${id}-primary`}
        label="Primary Text"
      >
        <Textarea
          aria-invalid={hasError(checksFor(row, "primary_text"))}
          className="min-h-16 text-sm"
          disabled={disabled}
          id={`${id}-primary`}
          onChange={(event) => {
            edit("primary_text", event.currentTarget.value)
          }}
          value={ad.primaryText}
        />
      </EditorField>
      {carousel ? (
        <CarouselCards
          args={args}
          checks={[...checksFor(row, "cards"), ...checksFor(row, "media")]}
          disabled={disabled}
          onEdit={onEdit}
          row={row}
        />
      ) : (
        <div className="grid gap-4 @2xl:grid-cols-2">
          <LabelledInput
            checks={checksFor(row, "headline")}
            counter={
              <LengthCounter
                length={ad.headline?.length ?? 0}
                limit={RECOMMENDED_LENGTHS.headline}
              />
            }
            disabled={disabled}
            id={`${id}-headline`}
            label="Headline"
            onChange={(value) => {
              edit("headline", value)
            }}
            value={ad.headline ?? ""}
          />
          <LabelledInput
            checks={checksFor(row, "description")}
            counter={
              <LengthCounter
                length={ad.description?.length ?? 0}
                limit={RECOMMENDED_LENGTHS.description}
              />
            }
            disabled={disabled}
            id={`${id}-description`}
            label="Description"
            onChange={(value) => {
              edit("description", blankToNull(value))
            }}
            placeholder="Optional"
            value={ad.description ?? ""}
          />
        </div>
      )}
      {ad.disclaimer ? (
        <div className="grid gap-0.5 text-sm">
          <p className={fieldLabelClass}>{titleCaseToken(ad.disclaimer.type, "Disclaimer")}</p>
          <p className="wrap-anywhere whitespace-pre-line">{ad.disclaimer.text}</p>
          {ad.disclaimer.url ? (
            <p className="text-muted-foreground text-sm wrap-anywhere">{ad.disclaimer.url}</p>
          ) : null}
        </div>
      ) : null}
      <LinkAndButton
        args={args}
        disabled={disabled}
        id={id}
        onEditSetting={onEditSetting}
        row={row}
      />
    </div>
  )
}

/** The ad's name, and the ad sets it is created in. */
function NameAndAdSet({ args, disabled, id, onEdit, row }: Omit<Edits, "onEditSetting">) {
  const { ad } = row
  return (
    <div className="grid gap-4 @2xl:grid-cols-2">
      <LabelledInput
        checks={checksFor(row, "name")}
        disabled={disabled}
        hint="only in Ads Manager"
        id={`${id}-name`}
        label="Ad Name"
        onChange={(value) => {
          onEdit(editAd(args, ad.index, "name", value))
        }}
        value={ad.name}
      />
      <EditorField hint="where the ad is created" id={`${id}-adset`} label="Ad Set">
        <AdSetPicker
          args={args}
          disabled={disabled}
          id={`${id}-adset`}
          index={ad.index}
          onChange={(adSets) => {
            onEdit(setAdSets(args, ad.index, adSets))
          }}
        />
      </EditorField>
    </div>
  )
}

/** The ad's website link and button, shared by every ad until one is given its own. */
function LinkAndButton({
  args,
  disabled,
  id,
  onEditSetting,
  row,
}: Pick<Edits, "args" | "disabled" | "id" | "onEditSetting" | "row">) {
  const { ad } = row
  const shared = !ad.post && args.ads.length > 1 && followsShared(ad)
  return (
    <div className="grid gap-4 @2xl:grid-cols-2">
      <LabelledInput
        checks={checksFor(row, "link")}
        disabled={disabled}
        hint={shared ? `shared by all ${String(args.ads.length)} ads` : undefined}
        id={`${id}-link`}
        inputMode="url"
        label="Website Link"
        onChange={(value) => {
          onEditSetting("link", blankToNull(value))
        }}
        value={row.link ?? ""}
      />
      <ButtonSelect
        allowed={row.allowedButtons}
        checks={checksFor(row, "call_to_action")}
        disabled={disabled}
        id={`${id}-button`}
        label={`Button for ${ad.name}`}
        onChange={(value) => {
          if (value) onEditSetting("call_to_action", value)
        }}
        value={row.callToAction}
      />
    </div>
  )
}

/** Feed and Stories side by side at the same width, with one note under both. */
function PreviewPanel({ args, row }: Pick<Edits, "args" | "row">) {
  const { ad } = row
  const carousel = ad.format === "carousel"
  const props = {
    callToAction: row.callToAction,
    cards: ad.cards.map((card) => ({
      media: card.media,
      headline: card.headline,
      description: card.description,
      callToAction: card.callToAction ?? row.callToAction,
    })),
    description: ad.description,
    domain: urlDomain(row.link),
    format: ad.format,
    headline: ad.headline,
    media: ad.media,
    pageId: args.pageId,
    pageName: args.pageName,
    primaryText: ad.primaryText,
    verticalMedia: ad.verticalMedia,
  }
  return (
    <div className="grid justify-items-center gap-3">
      <div className="flex flex-wrap items-start justify-center gap-4">
        <div className="grid w-60 gap-1.5">
          <p className="text-center text-sm font-medium">Feed</p>
          <AdPreview {...props} placement="feed" />
        </div>
        <div className="grid w-60 gap-1.5">
          <p className="text-center text-sm font-medium">Stories and Reels</p>
          <AdPreview {...props} placement="stories" />
        </div>
      </div>
      <p className="text-muted-foreground max-w-prose text-center text-sm">
        A close preview. Meta&apos;s own may differ slightly by placement.
        {carousel || ad.verticalMedia
          ? ""
          : ` With no vertical version, Meta fits the main ${ad.format} into Stories and Reels as shown.`}
      </p>
    </div>
  )
}

/** An existing post: shown as it runs, with only the settings a post takes. */
function PostAdBody({
  args,
  disabled,
  id,
  onEdit,
  onEditSetting,
  post,
  row,
}: Edits & { post: PostPreview }) {
  const instagram = post.source === "instagram"
  return (
    <div className="grid min-w-0 gap-4">
      <CheckMessages checks={checksFor(row, "post")} />
      <NameAndAdSet args={args} disabled={disabled} id={id} onEdit={onEdit} row={row} />
      <div className="w-full max-w-sm justify-self-center">
        <PostAdPreview
          callToAction={row.callToAction}
          domain={instagram ? urlDomain(row.link) : null}
          identityName={(instagram ? args.instagramName : null) ?? args.pageName}
          pageId={instagram ? null : args.pageId}
          post={post}
        />
      </div>
      <p className="text-muted-foreground text-sm">
        This post runs as it is, with its own text and media. To change them, ask the agent for a
        new ad instead.
      </p>
      {instagram ? (
        <LinkAndButton
          args={args}
          disabled={disabled}
          id={id}
          onEditSetting={onEditSetting}
          row={row}
        />
      ) : null}
    </div>
  )
}

/** The ad's media with Change, and its 9:16 vertical version to add, change, or remove. */
function MediaRow({
  args,
  disabled,
  onEdit,
  row,
}: Pick<Edits, "args" | "disabled" | "onEdit" | "row">) {
  const { ad } = row
  const kind = ad.format === "video" ? "video" : "image"
  const accept = [kind] as const
  return (
    <div className="grid min-w-0 gap-1.5">
      <span className={fieldLabelClass}>Media</span>
      <div className="flex flex-wrap items-center gap-3">
        <MediaFrame className="size-16 shrink-0 rounded-md" media={ad.media} shape="square" />
        <div className="grid min-w-0 flex-1 gap-0.5 text-sm">
          <span className="truncate">{ad.media?.label}</span>
          {ad.verticalMedia ? (
            <span className="text-muted-foreground truncate">
              9:16 version: {ad.verticalMedia.label}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MediaPicker
            accept={accept}
            description="Shown in Feed, and in Stories and Reels unless the ad has a vertical version."
            disabled={disabled}
            onChoose={(value) => {
              onEdit(setAdMedia(args, ad.index, "media", value))
            }}
            title={`Change the ${FORMAT_LABELS[ad.format]}`}
          >
            <ImageUpIcon />
            Change
          </MediaPicker>
          <MediaPicker
            accept={accept}
            description="A 9:16 version for Stories and Reels, so Meta doesn't crop the main one."
            disabled={disabled}
            onChoose={(value) => {
              onEdit(setAdMedia(args, ad.index, "vertical_media", value))
            }}
            title={ad.verticalMedia ? "Change the 9:16 Version" : "Add a 9:16 Version"}
          >
            {ad.verticalMedia ? <ImageUpIcon /> : <PlusIcon />}
            {ad.verticalMedia ? "Change 9:16 Version" : "Add 9:16 Version"}
          </MediaPicker>
          {ad.verticalMedia ? (
            <Button
              disabled={disabled}
              onClick={() => {
                onEdit(setAdMedia(args, ad.index, "vertical_media", null))
              }}
              type="button"
              variant="ghost"
            >
              <XIcon />
              Remove 9:16 Version
            </Button>
          ) : null}
        </div>
      </div>
      <CheckMessages checks={checksFor(row, "media")} />
    </div>
  )
}
