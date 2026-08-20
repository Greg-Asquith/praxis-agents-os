import { vi } from "vitest"

type FetchResponder = (
  input: RequestInfo | URL,
  init: RequestInit | undefined
) => Response | Promise<Response>

export function jsonResponse(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers)
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  return new Response(JSON.stringify(body), { ...init, headers })
}

export function stubFetch(response: Response | FetchResponder) {
  const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    response instanceof Response ? response : response(input, init)
  )
  vi.stubGlobal("fetch", fetchStub)
  return fetchStub
}

export function getFetchRequest(fetchStub: ReturnType<typeof stubFetch>, callIndex = 0) {
  const call = fetchStub.mock.calls[callIndex]
  if (!call) {
    throw new Error(`Expected fetch call ${String(callIndex + 1)}.`)
  }
  const [input, init = {}] = call
  const url = input instanceof URL ? input : new URL(typeof input === "string" ? input : input.url)
  return { init, url }
}

export function getJsonRequestBody(init: RequestInit): unknown {
  if (typeof init.body !== "string") {
    throw new Error("Expected a JSON request body.")
  }
  return JSON.parse(init.body) as unknown
}
