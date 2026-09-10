// apps/web/src/integrations/google_search_console/lib/write-args.ts

export function parseWritableSiteUrls(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 20) return null
  const sites = value.filter((site): site is string => typeof site === "string" && site.length > 0)
  return sites.length === value.length && new Set(sites).size === sites.length ? sites : null
}

export function isValidHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return (url.protocol === "http:" || url.protocol === "https:") && !url.username && !url.password
  } catch {
    return false
  }
}

export function matchesWritableSite(value: string, site: string): boolean {
  const url = new URL(value)
  if (site.startsWith("sc-domain:")) {
    const domain = site.slice("sc-domain:".length).toLowerCase()
    return (
      url.hostname.toLowerCase() === domain || url.hostname.toLowerCase().endsWith(`.${domain}`)
    )
  }
  try {
    const prefix = new URL(site)
    return url.origin === prefix.origin && url.pathname.startsWith(prefix.pathname)
  } catch {
    return false
  }
}
