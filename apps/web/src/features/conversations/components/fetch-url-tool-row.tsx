// apps/web/src/features/conversations/components/fetch-url-tool-row.tsx

import { BookPlusIcon, CheckIcon, FolderDownIcon, LinkIcon, Loader2Icon } from "lucide-react"
import type { ReactNode } from "react"

import { MarkdownContent } from "@/components/markdown/markdown-content"
import { FanOutSkeleton } from "@/components/tool-ui/fan-out-shell"
import { ToolResultCard } from "@/components/tool-ui/result-card"
import { useActionableConversation } from "@/components/tool-ui/tool-conversation-context"
import { ToolHeading } from "@/components/tool-ui/tool-heading"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useSaveFetchedPage } from "@/features/conversations/api/save-fetched-page"
import {
  type FetchUrlResult,
  fetchUrlArgsUrl,
  fetchUrlResult,
} from "@/features/conversations/components/fetch-url-result"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { useCreateDocumentFromUrlMutation } from "@/features/knowledge/api/create-document-from-url"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { canEditWorkspace } from "@/features/workspaces/permissions"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, pluralize, urlDomain } from "@/lib/format"

const HEADING = <ToolHeading icon={LinkIcon}>Fetch URL</ToolHeading>

export function FetchUrlToolRow({
  activity,
  defaultOpen = false,
}: {
  activity: ToolActivity
  defaultOpen?: boolean
}) {
  if (activity.status === "running") {
    const url = fetchUrlArgsUrl(activity.args)
    return url ? (
      <FanOutSkeleton
        running
        heading={HEADING}
        label={`Fetching ${url}…`}
        summary={`URL: ${url}`}
      />
    ) : null
  }
  const result = activity.status === "completed" ? fetchUrlResult(activity.result) : null
  if (!result) return null

  const details = [
    { label: "URL", value: result.finalUrl },
    { label: "Status", value: String(result.status) },
    { label: "Fetched", value: formatDateTime(result.fetchedAt) },
  ]
  if (result.redirects.length > 0) {
    const count = result.redirects.length
    details.push({ label: "Redirects", value: `${String(count)} ${pluralize(count, "Redirect")}` })
  }
  return (
    <ToolResultCard
      ariaLabel={`Fetched ${result.finalUrl}`}
      defaultOpen={defaultOpen}
      details={details}
      heading={HEADING}
      trailing={<StatusBadge result={result} />}
    >
      <div className="grid min-w-0 gap-3">
        {result.note ? <p className="text-muted-foreground text-xs">{result.note}</p> : null}
        {result.redirects.length > 0 ? (
          <ol aria-label="Redirects" className="text-muted-foreground grid gap-0.5 text-xs">
            {result.redirects.map((hop, index) => (
              <li className="break-all" key={`${String(index)}-${hop.location}`}>
                {hop.status} → {hop.location}
              </li>
            ))}
          </ol>
        ) : null}
        {result.content ? <FetchedContent result={result} content={result.content} /> : null}
        <FetchUrlActions result={result} />
      </div>
    </ToolResultCard>
  )
}

function StatusBadge({ result }: { result: FetchUrlResult }) {
  if (result.blockedBySite) return <Badge variant="warning">Blocked by Site</Badge>
  if (result.status >= 200 && result.status < 300) return <Badge variant="success">Done</Badge>
  return <Badge variant="destructive">Status {result.status}</Badge>
}

// Fetched HTML shows as source text; the UI never renders it.
function FetchedContent({ content, result }: { content: string; result: FetchUrlResult }) {
  return (
    <div
      aria-label="Fetched content"
      className="border-input bg-muted/40 max-h-[min(32rem,60vh)] min-w-0 overflow-y-auto overscroll-contain rounded-md border px-3 py-2.5"
    >
      {result.format === "markdown" ? (
        <MarkdownContent content={content} />
      ) : (
        <pre className="font-mono text-xs wrap-break-word whitespace-pre-wrap">{content}</pre>
      )}
    </div>
  )
}

function FetchUrlActions({ result }: { result: FetchUrlResult }) {
  const conversationId = useActionableConversation()
  return conversationId === null ? null : (
    <FetchUrlActionButtons conversationId={conversationId} result={result} />
  )
}

function FetchUrlActionButtons({
  conversationId,
  result,
}: {
  conversationId: string
  result: FetchUrlResult
}) {
  const { workspace } = useActiveWorkspace()
  const save = useSaveFetchedPage()
  const addToKnowledgeBase = useCreateDocumentFromUrlMutation()
  if (!canEditWorkspace(workspace.current_user_role)) return null

  const savedFileId = result.file?.id ?? save.data?.fileId
  const documentId = result.knowledgeBaseDocument?.id ?? addToKnowledgeBase.data?.id
  const savable = result.status >= 200 && result.status < 300 && result.format !== "unsupported"
  const error = save.error ?? addToKnowledgeBase.error
  return (
    <div className="grid justify-items-end gap-1">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {savedFileId ? (
          <Done href={`/files?fileId=${savedFileId}`} label="Saved to Files" />
        ) : savable ? (
          <ActionButton
            icon={<FolderDownIcon />}
            label="Save to Files"
            onClick={() => {
              save.mutate({ conversationId, url: result.requestedUrl })
            }}
            pending={save.isPending}
          />
        ) : null}
        {documentId ? (
          <Done href={`/knowledge/${documentId}`} label="Added to Knowledge Base" />
        ) : (
          <ActionButton
            icon={<BookPlusIcon />}
            label="Add to Knowledge Base"
            onClick={() => {
              addToKnowledgeBase.mutate({
                url: result.requestedUrl,
                title: result.title ?? urlDomain(result.requestedUrl) ?? result.requestedUrl,
                is_private: false,
              })
            }}
            pending={addToKnowledgeBase.isPending}
          />
        )}
      </div>
      {error ? (
        <p className="text-destructive text-right text-xs" role="alert">
          {getErrorMessage(error)}
        </p>
      ) : null}
    </div>
  )
}

function ActionButton({
  icon,
  label,
  onClick,
  pending,
}: {
  icon: ReactNode
  label: string
  onClick: () => void
  pending: boolean
}) {
  return (
    <Button disabled={pending} onClick={onClick} size="xs" type="button" variant="outline">
      {pending ? <Loader2Icon className="animate-spin motion-reduce:animate-none" /> : icon}
      {label}
    </Button>
  )
}

function Done({ href, label }: { href: string; label: string }) {
  return (
    <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
      <CheckIcon className="text-success size-3.5" />
      {label}.
      <a className="text-link hover:text-primary underline underline-offset-2" href={href}>
        Open
      </a>
    </p>
  )
}
