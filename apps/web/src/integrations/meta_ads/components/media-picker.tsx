// apps/web/src/integrations/meta_ads/components/media-picker.tsx

import { useInfiniteQuery } from "@tanstack/react-query"
import { Loader2Icon, SearchIcon, UploadIcon } from "lucide-react"
import { use, useId, useRef, useState, type ReactNode } from "react"

import {
  entityReferenceSearchQueryOptions,
  mergeEntityChoices,
} from "@/components/tool-ui/entity-reference-queries"
import { fieldWellClass } from "@/components/tool-ui/field-styles"
import { ToolConversationContext } from "@/components/tool-ui/tool-conversation-context"
import { useDebouncedValue } from "@/components/tool-ui/use-debounced-value"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MediaFrame } from "@/integrations/meta_ads/components/media-frame"
import {
  type MediaValue,
  previewMedia,
  type PreviewMedia,
} from "@/integrations/meta_ads/lib/create-ads-args"
import { getErrorMessage } from "@/lib/api/errors"
import { uploadWorkspaceFile } from "@/lib/api/workspace-file-upload"
import { cn } from "@/lib/utils"

type MediaType = "image" | "video"
type Source = "library" | "files"

// The create-ads tool declares both kinds on its ads field, so the card can look them up.
const LOOKUP = { toolName: "meta_ads_create_ads", fieldKey: "ads", dependentArgs: {} } as const
const KINDS: Record<Source, string> = { library: "meta_ads_media", files: "file" }
const SEARCH_DEBOUNCE_MS = 300
// Meta takes JPEG and PNG images from Files; videos go through its own upload first.
const IMAGE_FILE = /\.(jpe?g|png)$/i
const IMAGE_ACCEPT = ".jpg,.jpeg,.png,image/jpeg,image/png"
const NONE: readonly string[] = []

/** Opens a chooser for library media or workspace images, including a new upload. */
export function MediaPicker({
  accept,
  children,
  description,
  disabled,
  excluded = NONE,
  onChoose,
  size = "sm",
  title,
  triggerClassName,
  triggerLabel,
}: {
  accept: readonly MediaType[]
  children: ReactNode
  description: string
  disabled: boolean
  // Media keys already used where this choice goes, such as the other carousel cards.
  excluded?: readonly string[]
  onChoose: (value: MediaValue) => void
  size?: "sm" | "icon-xs"
  title: string
  triggerClassName?: string
  triggerLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const choose = (value: MediaValue) => {
    onChoose(value)
    setOpen(false)
  }
  const images = accept.includes("image")
  return (
    <>
      <Button
        aria-label={triggerLabel}
        className={triggerClassName}
        disabled={disabled}
        onClick={() => {
          setOpen(true)
        }}
        size={size}
        type="button"
        variant="outline"
      >
        {children}
      </Button>
      <Dialog onOpenChange={setOpen} open={open}>
        <DialogContent className="grid max-h-[85vh] grid-rows-[auto_minmax(0,1fr)] sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {open ? (
            images ? (
              <Tabs className="min-h-0" defaultValue="library">
                <TabsList aria-label="Where the media comes from" className="w-full">
                  <TabsTrigger value="library">Ad Account Library</TabsTrigger>
                  <TabsTrigger value="files">Workspace Files</TabsTrigger>
                </TabsList>
                <TabsContent className="min-h-0" value="library">
                  <ChoiceGrid
                    accept={accept}
                    excluded={excluded}
                    onChoose={choose}
                    source="library"
                  />
                </TabsContent>
                <TabsContent className="grid min-h-0 gap-3" value="files">
                  <UploadImage onChoose={choose} />
                  <ChoiceGrid
                    accept={accept}
                    excluded={excluded}
                    onChoose={choose}
                    source="files"
                  />
                </TabsContent>
              </Tabs>
            ) : (
              <ChoiceGrid accept={accept} excluded={excluded} onChoose={choose} source="library" />
            )
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}

function ChoiceGrid({
  accept,
  excluded,
  onChoose,
  source,
}: {
  accept: readonly MediaType[]
  excluded: readonly string[]
  onChoose: (value: MediaValue) => void
  source: Source
}) {
  const conversationId = use(ToolConversationContext)
  const id = useId()
  const [searchInput, setSearchInput] = useState("")
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DEBOUNCE_MS)
  const results = useInfiniteQuery({
    ...entityReferenceSearchQueryOptions({
      ...LOOKUP,
      conversationId: conversationId ?? "",
      entityKind: KINDS[source],
      pageSize: 24,
      search,
    }),
    enabled: conversationId !== null,
  })
  if (conversationId === null) {
    return <p className="text-muted-foreground text-sm">Open the conversation to choose media.</p>
  }
  const choices = mergeEntityChoices([], results.data?.pages ?? []).flatMap((choice) => {
    const preview = previewMedia(choice.value)
    if (!preview || !accept.includes(preview.mediaType)) return []
    if (source === "files" && !IMAGE_FILE.test(choice.label)) return []
    return [{ value: choice.value, preview, label: choice.label }]
  })
  return (
    <div className="grid min-h-0 gap-3">
      <div className="relative">
        <SearchIcon
          aria-hidden="true"
          className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2"
        />
        <Input
          aria-label={source === "files" ? "Search workspace Files" : "Search the media library"}
          className={cn(fieldWellClass, "pl-8")}
          id={`${id}-search`}
          onChange={(event) => {
            setSearchInput(event.currentTarget.value)
          }}
          placeholder="Search by name"
          value={searchInput}
        />
      </div>
      <div className="min-h-0 overflow-y-auto">
        {results.isPending ? (
          <Loading />
        ) : results.isError ? (
          <p className="text-destructive text-sm">{getErrorMessage(results.error)}</p>
        ) : choices.length === 0 ? (
          // A page can hold only Files that aren't images, so more may follow.
          results.hasNextPage ? null : (
            <p className="text-muted-foreground text-sm">{emptyMessage(source, accept)}</p>
          )
        ) : (
          <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {choices.map(({ value, preview, label }) => (
              <li key={preview.key}>
                <ChoiceButton
                  label={label}
                  onChoose={() => {
                    onChoose(value)
                  }}
                  preview={preview}
                  used={excluded.includes(preview.key)}
                />
              </li>
            ))}
          </ul>
        )}
        {results.hasNextPage ? (
          <Button
            className="mt-3 w-full"
            disabled={results.isFetchingNextPage}
            onClick={() => {
              void results.fetchNextPage()
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            {results.isFetchingNextPage ? "Loading" : "Show More"}
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function ChoiceButton({
  label,
  onChoose,
  preview,
  used,
}: {
  label: string
  onChoose: () => void
  preview: PreviewMedia
  used: boolean
}) {
  const note = !preview.ready ? "Processing" : used ? "Already used" : null
  return (
    <button
      aria-label={note ? `${label} (${note})` : `Choose ${label}`}
      className="group grid w-full cursor-pointer gap-1 text-left disabled:cursor-not-allowed disabled:opacity-50"
      disabled={note !== null}
      onClick={onChoose}
      type="button"
    >
      <MediaFrame
        className="group-hover:ring-ring rounded-md ring-1 ring-transparent"
        media={preview}
        shape="square"
      />
      <span className="text-muted-foreground truncate text-xs">{note ?? label}</span>
    </button>
  )
}

function UploadImage({ onChoose }: { onChoose: (value: MediaValue) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const upload = async (file: File) => {
    setError(null)
    if (!IMAGE_FILE.test(file.name)) {
      setError("Choose a JPEG or PNG image.")
      return
    }
    setUploading(true)
    try {
      const stored = await uploadWorkspaceFile(file)
      onChoose({ entity_kind: "file", entity_id: stored.id, label: stored.name })
    } catch (uploadError) {
      setError(getErrorMessage(uploadError))
    } finally {
      setUploading(false)
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        accept={IMAGE_ACCEPT}
        className="sr-only"
        onChange={(event) => {
          const file = event.currentTarget.files?.[0]
          event.currentTarget.value = ""
          if (file) void upload(file)
        }}
        ref={input}
        tabIndex={-1}
        type="file"
      />
      <Button
        disabled={uploading}
        onClick={() => input.current?.click()}
        size="sm"
        type="button"
        variant="outline"
      >
        {uploading ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}
        {uploading ? "Uploading" : "Upload from Computer"}
      </Button>
      <p className="text-muted-foreground text-xs">
        JPEG or PNG. It&apos;s saved to workspace Files.
      </p>
      {error ? <p className="text-destructive w-full text-sm">{error}</p> : null}
    </div>
  )
}

function Loading() {
  return (
    <p className="text-muted-foreground flex items-center gap-2 text-sm">
      <Loader2Icon aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
      Loading
    </p>
  )
}

function emptyMessage(source: Source, accept: readonly MediaType[]): string {
  if (source === "files") return "No JPEG or PNG images found in workspace Files."
  if (accept.length === 1 && accept[0] === "video") {
    return "No videos found. Ask the agent to upload one to the ad account first."
  }
  return "No media found in this ad account's library."
}
