// apps/web/src/components/mermaid/mermaid-diagram.tsx

import { useEffect, useId, useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type RenderState = { status: "rendered"; svg: string } | { status: "error"; message: string }

export function MermaidDiagram({
  className,
  source,
  title,
}: {
  className?: string
  source: string
  title: string
}) {
  const reactId = useId()
  const dark = useDarkMode()
  const renderKey = `${dark ? "dark" : "light"} ${source}`
  const [result, setResult] = useState<{ key: string; state: RenderState } | null>(null)

  useEffect(() => {
    let cancelled = false
    void renderMermaid(source, `mermaid-${reactId.replace(/[^a-zA-Z0-9-]/g, "")}`, dark)
      .then((svg) => {
        if (!cancelled) setResult({ key: renderKey, state: { status: "rendered", svg } })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setResult({
            key: renderKey,
            state: { status: "error", message: describeMermaidError(error) },
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [dark, reactId, renderKey, source])

  const state = result?.key === renderKey ? result.state : null
  if (!state) {
    return <Skeleton className={cn("h-40 w-full", className)} />
  }
  if (state.status === "error") {
    return (
      <div className={cn("grid gap-2", className)}>
        <p className="text-destructive text-xs" role="alert">
          This diagram could not be drawn: {state.message}
        </p>
        <pre className="bg-muted/30 overflow-auto rounded-lg border p-4 font-mono text-xs whitespace-pre-wrap">
          {source}
        </pre>
      </div>
    )
  }
  return (
    <div
      aria-label={title}
      className={cn("overflow-auto [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full", className)}
      // eslint-disable-next-line react-dom/no-dangerously-set-innerhtml -- Mermaid runs in strict security mode: its SVG is DOMPurify-sanitized and carries no scripts or click handlers. Only mermaid output may be inserted here.
      dangerouslySetInnerHTML={{ __html: state.svg }}
      role="img"
    />
  )
}

async function renderMermaid(source: string, id: string, dark: boolean) {
  const { default: mermaid } = await import("mermaid")
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: dark ? "dark" : "default",
    fontFamily: "inherit",
  })
  // Parse first so syntax errors surface without mermaid injecting an error graphic into the page.
  await mermaid.parse(source)
  const { svg } = await mermaid.render(id, source)
  return svg
}

function describeMermaidError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  const firstLine = message.split("\n")[0]?.trim() ?? ""
  return firstLine === "" ? "unknown error" : firstLine
}

function useDarkMode() {
  const [dark, setDark] = useState(() => isDarkMode())
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setDark(isDarkMode())
    })
    observer.observe(document.documentElement, { attributeFilter: ["class"], attributes: true })
    return () => {
      observer.disconnect()
    }
  }, [])
  return dark
}

function isDarkMode() {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark")
}
