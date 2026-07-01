// apps/web/src/lib/api/client.ts

import { env } from "@/config/env"
import { getCsrfToken } from "@/lib/api/csrf"
import { parseApiError } from "@/lib/api/errors"

type QueryValue = string | number | boolean | null | undefined

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown
  query?: Record<string, QueryValue>
}

type ApiRequestHeadersProvider = () => Record<string, string | null | undefined>

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"])

let apiRequestHeadersProvider: ApiRequestHeadersProvider | null = null

export function setApiRequestHeadersProvider(provider: ApiRequestHeadersProvider | null) {
  apiRequestHeadersProvider = provider
}

function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const url = new URL(
    path.startsWith("/") ? `${env.apiBaseUrl}${path}` : `${env.apiBaseUrl}/${path}`
  )

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
  const { url, init } = buildRequest(path, options)
  return fetch(url, init)
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
