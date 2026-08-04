// apps/web/src/components/tool-ui/html-content-frame.tsx

import { buildHtmlFrameDocument } from "@/lib/html-frame-document"
import { cn } from "@/lib/utils"

// Server-side sanitization (nh3) is the first layer wherever the HTML crosses
// the backend; this opaque-origin, script-less sandbox plus its CSP is the
// second. Do not add sandbox capabilities or allow-same-origin to recover
// auto-height — the fixed-height scroll container is the accepted trade.
const EMAIL_FRAME_CSP =
  "default-src 'none'; img-src data: https: http: cid:; style-src 'unsafe-inline'"
const EMAIL_FRAME_STYLES = [
  "<style>",
  "body{margin:12px;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;",
  "font-size:14px;line-height:1.5;color:#111827;background:#fff;word-break:break-word}",
  "img{max-width:100%;height:auto}",
  "</style>",
].join("")

export function HtmlContentFrame({
  className,
  html,
  title,
}: {
  className?: string
  html: string
  title: string
}) {
  return (
    <iframe
      className={cn("w-full bg-white", className)}
      sandbox=""
      srcDoc={buildHtmlFrameDocument({
        content: html,
        contentSecurityPolicy: EMAIL_FRAME_CSP,
        head: EMAIL_FRAME_STYLES,
      })}
      title={title}
    />
  )
}
