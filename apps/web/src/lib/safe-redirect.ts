// apps/web/src/lib/safe-redirect.ts

const UNSAFE_REDIRECT_CHARACTER = /[\s\p{Cc}]/u

export function safeRedirectPath(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.includes("\\") ||
    UNSAFE_REDIRECT_CHARACTER.test(value) ||
    !value.startsWith("/") ||
    value.startsWith("//")
  ) {
    return null
  }

  return value
}

export function authSuccessPath(redirect: unknown): string {
  return safeRedirectPath(redirect) ?? "/"
}

export function validateAuthRedirectSearch(search: Record<string, unknown>): {
  redirect?: string
} {
  const redirect = safeRedirectPath(search["redirect"])
  return redirect ? { redirect } : {}
}

export function invitationTokenFromRedirect(redirect: string | null): string | null {
  if (!redirect) return null

  const target = new URL(redirect, "https://local.invalid")
  if (target.pathname !== "/invitations/accept") return null

  const token = target.searchParams.get("token")?.trim() ?? ""
  return token.length > 0 && token.length <= 512 ? token : null
}
