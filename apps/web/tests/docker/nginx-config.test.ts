import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { renderSecurityHeaders } from "../../docker/render-nginx-config.mjs"

const webRoot = fileURLToPath(new URL("../../", import.meta.url))
const nginxConfig = readFileSync(`${webRoot}nginx.conf`, "utf8")

describe("production nginx security headers", () => {
  it("includes the generated policy for the shell, assets, and SPA fallback", () => {
    const include = "include /etc/nginx/snippets/praxis-security-headers.conf;"

    expect(nginxConfig.match(new RegExp(include.replaceAll(".", "\\."), "g"))).toHaveLength(3)
    expect(nginxConfig).toContain("location /assets/")
    expect(nginxConfig).toContain("location = /index.html")
    expect(nginxConfig).toContain("location /")
  })

  it("renders a restrictive origin-pinned policy without HSTS for local HTTP", () => {
    const headers = renderSecurityHeaders({
      apiBaseUrl: "http://localhost:8000/api/v1",
      assetOrigins: "https://files.example.com",
    })

    expect(headers).toContain("default-src 'self'")
    expect(headers).toContain("script-src 'self'")
    expect(headers).toContain("connect-src 'self' http://localhost:8000 https://files.example.com")
    expect(headers).toContain(
      "img-src 'self' data: blob: http://localhost:8000 https://files.example.com"
    )
    expect(headers).toContain('add_header X-Frame-Options "DENY" always;')
    expect(headers).not.toContain("Strict-Transport-Security")
    expect(headers).not.toMatch(/(?:script-src|connect-src)[^;]*\*/)
  })

  it("adds the required HSTS policy for HTTPS deployments", () => {
    const headers = renderSecurityHeaders({
      apiBaseUrl: "https://api.example.com/api/v1",
      httpsOnly: true,
    })

    expect(headers).toContain(
      'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;'
    )
  })

  it("rejects wildcard and non-HTTP origins", () => {
    expect(() => renderSecurityHeaders({ apiBaseUrl: "https://*.example.com/api/v1" })).toThrow(
      "wildcard"
    )
    expect(() => renderSecurityHeaders({ apiBaseUrl: "javascript:alert(1)" })).toThrow("HTTP(S)")
  })
})
