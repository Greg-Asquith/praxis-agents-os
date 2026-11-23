// apps/web/src/features/conversations/components/tools/web/web-error-text.ts

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
