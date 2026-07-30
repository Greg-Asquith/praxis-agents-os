// apps/web/src/lib/full-document-redirect.ts

import { redirect } from "@tanstack/react-router"

export function fullDocumentRedirect(path: string): never {
  const target = new URL(path, window.location.origin)
  if (target.origin !== window.location.origin) {
    throw new Error("Refusing to redirect to a different origin.")
  }

  redirect({
    href: target.href,
    reloadDocument: true,
    replace: true,
    throw: true,
  })
  throw new Error("TanStack Router did not throw the full-document redirect.")
}
