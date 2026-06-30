// apps/web/src/lib/api/client.ts

import { env } from "@/config/env"
import { getCsrfToken } from "@/lib/api/csrf"
import { ApiError, type ApiProblem } from "@/lib/api/errors"
import { getActiveWorkspaceSlug } from "@/lib/api/workspace-context"

type QueryValue = string | number | boolean | null | undefined

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown
  query?: Record<string, QueryValue>
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"])

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

  const activeWorkspace = getActiveWorkspaceSlug()
  if (activeWorkspace) {
    requestHeaders.set("X-Workspace", activeWorkspace)
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

async function parseProblem(response: Response) {
  const contentType = response.headers.get("content-type") ?? ""
  if (!contentType.includes("application/json")) {
    return null
  }

  try {
    return (await response.json()) as ApiProblem
  } catch {
    return null
  }
}

function problemMessage(problem: ApiProblem | null, fallback: string) {
  return problem?.detail ?? problem?.message ?? problem?.title ?? fallback
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}) {
  const { url, init } = buildRequest(path, options)
  const response = await fetch(url, init)

  if (!response.ok) {
    const problem = await parseProblem(response)
    throw new ApiError({
      status: response.status,
      message: problemMessage(problem, response.statusText),
      problem,
    })
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
