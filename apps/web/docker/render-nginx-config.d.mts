// apps/web/docker/render-nginx-config.d.mts

export function renderSecurityHeaders(options: {
  apiBaseUrl: string
  assetOrigins?: string
  httpsOnly?: boolean
}): string
