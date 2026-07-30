// apps/web/src/lib/html-frame-document.ts

export const INTERACTIVE_HTML_FRAME_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  "img-src data: blob:",
  "font-src data:",
  "connect-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "object-src 'none'",
].join("; ")

export function buildHtmlFrameDocument({
  content,
  contentSecurityPolicy,
  head = "",
}: {
  content: string
  contentSecurityPolicy: string
  head?: string
}) {
  return [
    "<!doctype html><html><head>",
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${contentSecurityPolicy}">`,
    head,
    "</head><body>",
    content,
    "</body></html>",
  ].join("")
}
