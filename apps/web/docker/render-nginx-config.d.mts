// apps/web/deocker/render-nginx-config.d.mts

export function renderSecurityHeaders(options: {
  apiBaseUrl: string
  assetOrigins?: string
  httpsOnly?: boolean
}): string
