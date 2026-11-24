// apps/web/src/features/conversations/components/tools/web/web-error-text.ts

import type { WebRedirect } from "@/features/conversations/components/tools/web/web-redirects"

// Why a URL wasn't checked or tested, for a non-technical reader.
const ERROR_TEXT: Record<string, string> = {
  blocked_domain: "On the blocked domain list",
  connect_failure: "The site didn't accept the connection",
  dns_failure: "The address doesn't exist",
  invalid_url: "Not a web address",
  key_rejected: "Google rejected the PageSpeed key",
  non_public_address: "Not a public address",
  not_checked: "Not reached in time",
  page_error: "The page failed during the test",
  page_unreachable: "Google couldn't load the page",
  protocol_failure: "The site sent an unreadable response",
  quota_exceeded: "Google's test limit was reached",
  redirect_without_location: "Redirects to nowhere",
  service_error: "PageSpeed Insights didn't respond",
  timeout: "Took too long to respond",
  tls_failure: "The secure connection failed",
  too_large: "The response is too large",
  too_many_redirects: "Too many redirects",
  unsupported_port: "Not a public address",
}

export function webErrorText(errorClass: string | null): string | null {
  return errorClass === null ? null : (ERROR_TEXT[errorClass] ?? null)
}

// What a site's HTTP status means, for a non-technical reader; cards keep the code in their details.
const STATUS_TEXT: Record<number, string> = {
  200: "OK",
  204: "Empty Page",
  301: "Moved Permanently",
  302: "Moved Temporarily",
  303: "Sent Elsewhere",
  304: "Not Modified",
  307: "Moved Temporarily",
  308: "Moved Permanently",
  400: "Bad Request",
  401: "Needs Sign-In",
  403: "Access Refused",
  404: "Not Found",
  405: "Request Not Allowed",
  408: "Timed Out",
  410: "Gone",
  429: "Too Many Requests",
  451: "Blocked for Legal Reasons",
  500: "Server Error",
  502: "Server Error",
  503: "Site Unavailable",
  504: "Timed Out",
}

export function httpStatusText(status: number): string {
  const text = STATUS_TEXT[status]
  if (text) return text
  if (status >= 500) return "Server Error"
  if (status >= 400) return "Request Refused"
  return status >= 300 ? "Redirected" : "OK"
}

/** Says what each hop did, such as "Moved permanently, then moved temporarily". */
export function redirectChainText(redirects: WebRedirect[]): string {
  const text = redirects.map((hop) => httpStatusText(hop.status).toLowerCase()).join(", then ")
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function redirectCodes(redirects: WebRedirect[]): string {
  return redirects.map((hop) => String(hop.status)).join(" → ")
}
