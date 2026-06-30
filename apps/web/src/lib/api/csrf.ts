// apps/web/src/lib/api/csrf.ts

function getCookie(name: string) {
  if (typeof document === "undefined") {
    return null
  }

  return (
    document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${name}=`))
      ?.slice(name.length + 1) ?? null
  )
}

export function getCsrfToken() {
  const value = getCookie("csrf")
  return value ? decodeURIComponent(value) : null
}
