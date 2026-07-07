// apps/web/src/config/env.ts

const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1"
const configuredApiBaseUrl: unknown = import.meta.env.VITE_API_BASE_URL

function stripTrailingSlash(value: string) {
  return value.replace(/\/+$/, "")
}

export const env = {
  apiBaseUrl: stripTrailingSlash(
    typeof configuredApiBaseUrl === "string" && configuredApiBaseUrl.length > 0
      ? configuredApiBaseUrl
      : DEFAULT_API_BASE_URL
  ),
}
