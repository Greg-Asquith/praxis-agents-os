// apps/web/src/routes/recovery-paths.ts

export function currentPathname() {
  if (typeof window === "undefined") {
    return "/"
  }

  return window.location.pathname
}

export function isAuthRecoveryPath(pathname: string) {
  return (
    pathname.startsWith("/login") ||
    pathname.startsWith("/register") ||
    pathname.startsWith("/oauth")
  )
}
