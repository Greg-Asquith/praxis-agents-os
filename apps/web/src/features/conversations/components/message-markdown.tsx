// apps/web/src/features/conversations/components/message-markdown.tsx

import { isValidElement, memo, useMemo, type ReactNode } from "react"
import { CheckIcon, CopyIcon } from "lucide-react"
import { marked } from "marked"
import ReactMarkdown, { type Components, type Options } from "react-markdown"
import rehypeRaw from "rehype-raw"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"
import remarkGfm from "remark-gfm"

import { Button } from "@/components/ui/button"
import {
  MarkdownTable,
  MarkdownTableCell,
  MarkdownTableHead,
  MarkdownTableHeader,
  MarkdownTableRow,
} from "@/features/conversations/components/markdown-table"
import { useClipboardCopy } from "@/hooks/use-clipboard-copy"
import { reactNodeToText } from "@/lib/react-node"
import { cn } from "@/lib/utils"

const MAX_MARKDOWN_LENGTH = 200_000
const REMARK_PLUGINS = [remarkGfm]
const SANITIZE_SCHEMA = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "mark", "u"],
  attributes: {
    ...defaultSchema.attributes,
    "*": [...(defaultSchema.attributes?.["*"] ?? []), "className"],
  },
}
const REHYPE_PLUGINS: NonNullable<Options["rehypePlugins"]> = [
  rehypeRaw,
  [rehypeSanitize, SANITIZE_SCHEMA],
]

export const MessageMarkdown = memo(function MessageMarkdown({
  className,
  content,
}: {
  className?: string
  content: string
}) {
  const shouldParseMarkdown = content.length <= MAX_MARKDOWN_LENGTH
  const blocks = useMemo(
    () => (shouldParseMarkdown ? parseMarkdownIntoBlocks(content) : []),
    [content, shouldParseMarkdown]
  )

  if (!shouldParseMarkdown) {
    return (
      <pre
        className={cn(
          "text-foreground text-sm leading-7 wrap-break-word whitespace-pre-wrap",
          className
        )}
      >
        {content}
      </pre>
    )
  }

  return (
    <div className={cn("text-foreground min-w-0 text-sm leading-7", className)}>
      {blocks.map((block, index) => (
        <MemoizedMarkdownBlock
          key={`${String(index)}:${String(block.length)}`}
          components={MARKDOWN_COMPONENTS}
          content={block}
        />
      ))}
    </div>
  )
})

const MemoizedMarkdownBlock = memo(
  function MarkdownBlock({ components, content }: { components: Components; content: string }) {
    return (
      <ReactMarkdown
        components={components}
        rehypePlugins={REHYPE_PLUGINS}
        remarkPlugins={REMARK_PLUGINS}
      >
        {content}
      </ReactMarkdown>
    )
  },
  (previous, next) => previous.content === next.content
)

const MARKDOWN_COMPONENTS: Components = markdownComponents()

function markdownComponents(): Components {
  return {
    a: ({ children, href, ...props }) => {
      const isExternal = typeof href === "string" && /^https?:\/\//i.test(href)
      return (
        <a
          className="text-primary wrap-break-word underline underline-offset-2 hover:opacity-80"
          href={href}
          rel={isExternal ? "noopener noreferrer" : undefined}
          target={isExternal ? "_blank" : undefined}
          {...props}
        >
          {children}
        </a>
      )
    },
    blockquote: ({ children, ...props }) => (
      <blockquote
        className="border-border text-muted-foreground my-4 border-l-2 pl-4 italic"
        {...props}
      >
        {children}
      </blockquote>
    ),
    code: ({ children, className, ...props }) => {
      const isInline = !className?.includes("language-")
      if (!isInline) {
        return (
          <code className={className} {...props}>
            {children}
          </code>
        )
      }

      return (
        <code
          className="bg-muted text-foreground rounded px-1.5 py-0.5 font-mono text-[0.85em]"
          {...props}
        >
          {children}
        </code>
      )
    },
    del: ({ children, ...props }) => (
      <del className="line-through" {...props}>
        {children}
      </del>
    ),
    em: ({ children, ...props }) => <em {...props}>{children}</em>,
    h1: ({ children, ...props }) => (
      <h1 className="mt-6 mb-3 text-xl font-semibold first:mt-0" {...props}>
        {children}
      </h1>
    ),
    h2: ({ children, ...props }) => (
      <h2 className="mt-5 mb-2 text-lg font-semibold first:mt-0" {...props}>
        {children}
      </h2>
    ),
    h3: ({ children, ...props }) => (
      <h3 className="mt-4 mb-2 text-base font-semibold first:mt-0" {...props}>
        {children}
      </h3>
    ),
    h4: ({ children, ...props }) => (
      <h4 className="mt-4 mb-2 text-sm font-semibold first:mt-0" {...props}>
        {children}
      </h4>
    ),
    hr: (props) => <hr className="border-border my-5" {...props} />,
    input: ({ checked, disabled, type, ...props }) => {
      if (type !== "checkbox") {
        return <input type={type} {...props} />
      }

      return (
        <input
          checked={checked}
          className="mr-2 align-middle accent-current"
          disabled={disabled}
          readOnly
          type="checkbox"
          {...props}
        />
      )
    },
    li: ({ children, className, ...props }) => (
      <li
        className={cn(
          "[&>p]:mb-0 [&>p:not(:last-child)]:mb-2",
          typeof className === "string" && className.includes("task-list-item") && "list-none"
        )}
        {...props}
      >
        {children}
      </li>
    ),
    mark: ({ children, ...props }) => (
      <mark className="rounded bg-amber-200 px-0.5 text-amber-950" {...props}>
        {children}
      </mark>
    ),
    ol: ({ children, start, ...props }) => (
      <ol className="my-3 list-decimal pl-5" start={start} {...props}>
        {children}
      </ol>
    ),
    p: ({ children, ...props }) => (
      <p className="mb-3 wrap-break-word whitespace-pre-wrap last:mb-0" {...props}>
        {children}
      </p>
    ),
    pre: ({ children }) => {
      if (isValidElement(children)) {
        const props = children.props as { children?: ReactNode; className?: string }
        return (
          <MarkdownCodeBlock
            code={reactNodeToText(props.children).replace(/\n$/, "")}
            language={getCodeLanguage(props.className)}
          />
        )
      }

      return <pre>{children}</pre>
    },
    strong: ({ children, ...props }) => (
      <strong className="font-semibold" {...props}>
        {children}
      </strong>
    ),
    table: ({ children }) => <MarkdownTable>{children}</MarkdownTable>,
    tbody: ({ children, ...props }) => <tbody {...props}>{children}</tbody>,
    td: MarkdownTableCell,
    th: MarkdownTableHeader,
    thead: MarkdownTableHead,
    tr: MarkdownTableRow,
    u: ({ children, ...props }) => (
      <u className="underline underline-offset-2" {...props}>
        {children}
      </u>
    ),
    ul: ({ children, className, ...props }) => (
      <ul
        className={cn(
          "my-3 pl-5",
          typeof className === "string" && className.includes("contains-task-list")
            ? "list-none"
            : "list-disc"
        )}
        {...props}
      >
        {children}
      </ul>
    ),
  }
}

function MarkdownCodeBlock({ code, language }: { code: string; language: string }) {
  const { copied, copy } = useClipboardCopy()

  function handleCopy() {
    void copy(code)
  }

  return (
    <div className="group/code my-3 overflow-hidden rounded-lg border">
      <div className="bg-muted/60 flex items-center justify-between gap-3 border-b px-3 py-1.5">
        <span className="text-muted-foreground font-mono text-xs">{language}</span>
        <Button
          aria-label={copied ? "Copied code" : "Copy code"}
          size="icon-xs"
          type="button"
          variant="ghost"
          onClick={handleCopy}
        >
          {copied ? <CheckIcon /> : <CopyIcon />}
        </Button>
      </div>
      <pre className="bg-background max-w-full overflow-x-auto px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre">
        <code>{code}</code>
      </pre>
    </div>
  )
}

function parseMarkdownIntoBlocks(markdown: string): string[] {
  try {
    return marked
      .lexer(markdown)
      .map((token) => token.raw)
      .filter((raw) => raw.length > 0)
  } catch {
    return [markdown]
  }
}

function getCodeLanguage(className: string | undefined): string {
  if (!className) {
    return "text"
  }

  const match = /language-(\S+)/.exec(className)
  return match?.[1] ?? "text"
}
