// apps/web/docker/render-nginx-config.mjs

import { writeFileSync } from "node:fs"

function parseOrigin(value, name) {
  let url
  try {
    url = new URL(value)
  } catch {
    throw new Error(`${name} must be an absolute HTTP(S) URL.`)
  }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error(`${name} must be an absolute HTTP(S) URL without credentials.`)
  }
  if (url.hostname.includes("*")) {
    throw new Error(`${name} must not contain a wildcard host.`)
  }
  return url.origin
}

function parseAdditionalOrigins(value) {
  if (!value?.trim()) {
    return []
  }
  return value
    .split(",")
    .map((origin, index) => parseOrigin(origin.trim(), `WEB_PUBLIC_ASSET_ORIGINS[${index}]`))
}

export function renderSecurityHeaders({ apiBaseUrl, assetOrigins = "", httpsOnly = false }) {
  const apiOrigin = parseOrigin(apiBaseUrl, "VITE_API_BASE_URL")
  const mediaOrigins = [...new Set([apiOrigin, ...parseAdditionalOrigins(assetOrigins)])]
  const csp = [
    "default-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    `connect-src 'self' ${mediaOrigins.join(" ")}`,
    `frame-src 'self' ${apiOrigin}`,
    `img-src 'self' data: blob: ${mediaOrigins.join(" ")}`,
    `media-src 'self' data: blob: ${mediaOrigins.join(" ")}`,
  ].join("; ")

  return [
    `add_header Content-Security-Policy "${csp}" always;`,
    'add_header X-Content-Type-Options "nosniff" always;',
    'add_header X-Frame-Options "DENY" always;',
    'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
    ...(httpsOnly
      ? ['add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;']
      : []),
    "",
  ].join("\n")
}

function main() {
  const apiBaseUrl = process.env.VITE_API_BASE_URL
  if (!apiBaseUrl) {
    throw new Error("VITE_API_BASE_URL is required to build the web container.")
  }
  const rendered = renderSecurityHeaders({
    apiBaseUrl,
    assetOrigins: process.env.WEB_PUBLIC_ASSET_ORIGINS,
    httpsOnly: process.env.WEB_HTTPS_ONLY === "true",
  })
  writeFileSync("/tmp/praxis-security-headers.conf", rendered)
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  main()
}
