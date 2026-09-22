// apps/web/src/integrations/sharepoint/lib/write-location.ts

export function sharePointWriteLocation(path: string): string {
  const graphPath = /^\/(?:drives\/[^/]+|drive)\/root:(.*)$/s.exec(path)
  const relativePath = graphPath ? graphPath[1] : path
  if (relativePath === "" && graphPath) return "Library root"
  if (!relativePath?.startsWith("/") || /^\/drives?(?:\/|$)/.test(relativePath))
    return "Location unavailable"
  if (/^\/+$/.test(relativePath)) return "Library root"
  return relativePath
}
