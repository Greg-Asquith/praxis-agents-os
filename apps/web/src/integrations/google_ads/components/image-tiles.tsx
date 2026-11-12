// apps/web/src/integrations/google_ads/components/image-tiles.tsx

import { useQuery } from "@tanstack/react-query"
import { ImageIcon, PlusIcon, XIcon } from "lucide-react"
import { use, useState } from "react"

import { providerPreviewQueryOptions } from "@/components/tool-ui/provider-preview-queries"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { EntityChoice } from "@/features/tools/types"
import { EntitySearch } from "@/integrations/ads/components/entity-search"
import {
  IMAGE_TYPE_LABELS,
  imageFromChoice,
  imageProblem,
  type DraftImage,
  type ImageType,
  type LogoType,
  type PerformanceMaxChecks,
} from "@/integrations/google_ads/lib/performance-max"
import { cn } from "@/lib/utils"

type Shape = ImageType | LogoType

const IMAGE_DATA_URL = /^data:image\/(?:jpeg|png);base64,[A-Za-z0-9+/]+={0,2}$/

/** Chosen images as picture tiles, each with its shape, and a way to add more. */
export function ImageTiles<T extends Shape>({
  addLabel,
  checks,
  disabled,
  fieldKey,
  images,
  onChange,
  shapeFor,
  shapes,
}: {
  addLabel: string
  checks: PerformanceMaxChecks | null
  disabled: boolean
  fieldKey: string
  images: readonly DraftImage<T>[]
  onChange: (images: DraftImage<T>[]) => void
  shapeFor: (choice: EntityChoice) => T
  shapes: readonly T[]
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div className="grid min-w-0 gap-3">
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-x-3 gap-y-4">
        {images.map((image, at) => (
          <ImageTile
            key={`${image.assetId}:${image.fieldType}`}
            checks={checks}
            disabled={disabled}
            image={image}
            onRemove={() => {
              onChange(images.filter((_, index) => index !== at))
            }}
            onShape={(fieldType) => {
              onChange(images.map((item, index) => (index === at ? { ...item, fieldType } : item)))
            }}
            shapes={shapes}
          />
        ))}
        <li>
          <button
            className="text-muted-foreground hover:bg-muted/60 hover:text-foreground flex h-28 w-full flex-col items-center justify-center gap-1 rounded-md border border-dashed text-sm transition-colors disabled:pointer-events-none disabled:opacity-50"
            disabled={disabled || adding}
            onClick={() => {
              setAdding(true)
            }}
            type="button"
          >
            <PlusIcon className="size-4" />
            {addLabel}
          </button>
        </li>
      </ul>
      {adding ? (
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <EntitySearch
              disabled={disabled}
              entityKind="google_ads_asset"
              fieldKey={fieldKey}
              isTaken={(choice) =>
                choice.value["asset_type"] !== "IMAGE" ||
                images.some((image) => image.assetId === String(choice.value["asset_id"]))
              }
              label="Search uploaded images"
              onChoose={(choice) => {
                const image = imageFromChoice(choice, shapeFor(choice))
                if (image) onChange([...images, image])
                setAdding(false)
              }}
              placeholder="Search uploaded images by name"
              toolName="google_ads_create_campaign"
            />
          </div>
          <Button
            onClick={() => {
              setAdding(false)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            Cancel
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function ImageTile<T extends Shape>({
  checks,
  disabled,
  image,
  onRemove,
  onShape,
  shapes,
}: {
  checks: PerformanceMaxChecks | null
  disabled: boolean
  image: DraftImage<T>
  onRemove: () => void
  onShape: (shape: T) => void
  shapes: readonly T[]
}) {
  const facts = checks?.images.get(image.assetId)
  const problem = imageProblem(image, checks)
  const picture = useImagePicture(image)
  return (
    <li className="grid min-w-0 content-start gap-2">
      <div
        className={cn(
          "group bg-muted/60 relative flex h-28 items-center justify-center overflow-hidden rounded-md p-2",
          problem && "ring-destructive/60 ring-1"
        )}
      >
        {picture.src ? (
          <img
            alt={image.label}
            className="max-h-full max-w-full rounded-sm object-contain"
            src={picture.src}
          />
        ) : (
          <ImageIcon
            className={cn("text-muted-foreground size-5", picture.loading && "animate-pulse")}
          />
        )}
        <Button
          aria-label={`Remove ${image.label}`}
          className="bg-background/90 absolute top-1.5 right-1.5 opacity-0 shadow-xs group-hover:opacity-100 focus-visible:opacity-100"
          disabled={disabled}
          onClick={onRemove}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          <XIcon />
        </Button>
      </div>
      <div className="grid min-w-0 gap-0.5">
        <span className="truncate text-sm" title={image.label}>
          {image.label}
        </span>
        <span
          className={cn(
            "text-xs tabular-nums",
            problem ? "text-destructive" : "text-muted-foreground"
          )}
        >
          {problem ??
            (facts ? `${String(facts.width)} × ${String(facts.height)}` : "Size not checked yet")}
        </span>
      </div>
      <Select<string>
        disabled={disabled}
        onValueChange={(next) => {
          const shape = shapes.find((item) => item === next)
          if (shape) onShape(shape)
        }}
        value={image.fieldType}
      >
        <SelectTrigger
          aria-label={`Shape of ${image.label}`}
          className="bg-muted/60 hover:bg-muted w-full border-transparent"
          size="sm"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            {shapes.map((shape) => (
              <SelectItem key={shape} label={IMAGE_TYPE_LABELS[shape]} value={shape}>
                {IMAGE_TYPE_LABELS[shape]}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </li>
  )
}

// Reads the image from Google through the API, so it stays inside the page's content policy.
function useImagePicture(image: DraftImage<string>): { loading: boolean; src: string | null } {
  const conversationId = use(ToolConversationContext)
  const customerId = image.reference["customer_id"]
  const scopeId = typeof customerId === "string" ? customerId : null
  const query = useQuery({
    ...providerPreviewQueryOptions({
      conversationId,
      providerKey: "google_ads",
      kind: "google_ads_image",
      scopeId: scopeId ?? "",
      ref: image.assetId,
    }),
    enabled: conversationId !== null && scopeId !== null,
  })
  const content = query.data?.content_type === "image" ? query.data.content : null
  return {
    loading: query.isLoading,
    src: content && IMAGE_DATA_URL.test(content) ? content : null,
  }
}
