// apps/web/src/features/conversations/components/conversation-markdown-content.tsx

import { useState, type MouseEvent } from "react"

import {
  MarkdownAnchor,
  MarkdownContent,
  type MarkdownAnchorProps,
} from "@/components/markdown/markdown-content"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { workspaceFileIdFromHref } from "@/features/conversations/file-links"
import { getErrorMessage } from "@/lib/api/errors"
import { reactNodeToText } from "@/lib/react-node"

export function ConversationMarkdownContent({
  className,
  content,
}: {
  className?: string
  content: string
}) {
  return (
    <MarkdownContent
      {...(className ? { className } : {})}
      content={content}
      linkComponent={ConversationMarkdownLink}
    />
  )
}

function ConversationMarkdownLink({ children, href, node: _node, ...props }: MarkdownAnchorProps) {
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const fileId = workspaceFileIdFromHref(href)
  if (fileId === null) {
    return (
      <MarkdownAnchor href={href} {...props}>
        {children}
      </MarkdownAnchor>
    )
  }
  const workspaceFileId = fileId

  async function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return
    }
    event.preventDefault()
    if (downloading) {
      return
    }
    setError(null)
    setDownloading(true)
    try {
      await openWorkspaceFile(
        { fileId: workspaceFileId, name: reactNodeToText(children).trim() || "workspace-file" },
        { forceDownload: true }
      )
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <span>
      <a
        aria-busy={downloading}
        className="text-link hover:text-primary wrap-break-word underline underline-offset-2"
        data-workspace-file-download={workspaceFileId}
        href={href}
        onClick={(event) => void handleClick(event)}
        {...props}
      >
        {children}
      </a>
      {error ? (
        <span className="text-destructive ml-2 text-xs" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  )
}
