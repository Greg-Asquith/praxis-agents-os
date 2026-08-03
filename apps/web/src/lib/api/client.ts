// apps/web/src/lib/api/client.ts

import { env } from "@/config/env"
import { getCsrfToken } from "@/lib/api/csrf"
import { parseApiError } from "@/lib/api/errors"

type QueryValue = string | number | boolean | null | undefined

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown
  query?: Record<string, QueryValue>
  sessionPolicy?: "required" | "optional"
}

type ApiRequestHeadersProvider = () => Record<string, string | null | undefined>
type ApiUnauthorizedHandler = () => void

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"])

let apiRequestHeadersProvider: ApiRequestHeadersProvider | null = null
let apiUnauthorizedHandler: ApiUnauthorizedHandler | null = null

export function setApiRequestHeadersProvider(provider: ApiRequestHeadersProvider | null) {
  apiRequestHeadersProvider = provider
}

export function setApiUnauthorizedHandler(handler: ApiUnauthorizedHandler | null) {
  apiUnauthorizedHandler = handler
}

export function reportSessionLoss() {
  apiUnauthorizedHandler?.()
}

export function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const apiBaseUrl = new URL(env.apiBaseUrl)
  const url = new URL(
    path.startsWith("/") ? `${env.apiBaseUrl}${path}` : `${env.apiBaseUrl}/${path}`
  )
  const apiBasePathPrefix = apiBaseUrl.pathname.endsWith("/")
    ? apiBaseUrl.pathname
    : `${apiBaseUrl.pathname}/`
  const isWithinApiBase =
    url.origin === apiBaseUrl.origin &&
    (url.pathname === apiBaseUrl.pathname || url.pathname.startsWith(apiBasePathPrefix))

  if (!isWithinApiBase) {
    throw new Error("API request path escaped the configured API base URL.")
  }

  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value))
    }
  }

  return url
}

function buildRequest(
  path: string,
  { body, headers, method = "GET", query, ...init }: ApiRequestOptions = {}
): { url: URL; init: RequestInit } {
  const normalizedMethod = method.toUpperCase()
  const requestHeaders = new Headers(headers)
  if (!requestHeaders.has("Accept")) {
    requestHeaders.set("Accept", "application/json")
  }

  if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json")
  }

  for (const [key, value] of Object.entries(apiRequestHeadersProvider?.() ?? {})) {
    if (value !== undefined && value !== null) {
      requestHeaders.set(key, value)
    }
  }

  if (UNSAFE_METHODS.has(normalizedMethod)) {
    const csrfToken = getCsrfToken()
    if (csrfToken) {
      requestHeaders.set("X-CSRF-Token", csrfToken)
    }
  }

  const requestInit: RequestInit = {
    ...init,
    credentials: "include",
    headers: requestHeaders,
    method: normalizedMethod,
  }

  if (body !== undefined) {
    requestInit.body = JSON.stringify(body)
  }

  return { url: buildUrl(path, query), init: requestInit }
}

export async function apiFetch(path: string, options: ApiRequestOptions = {}) {
  const { sessionPolicy = "required", ...requestOptions } = options
  const { url, init } = buildRequest(path, requestOptions)
  const response = await fetch(url, init)

  if (response.status === 401 && sessionPolicy === "required") {
    reportSessionLoss()
  }

  return response
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}) {
  const response = await apiFetch(path, options)

  if (!response.ok) {
    throw await parseApiError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
