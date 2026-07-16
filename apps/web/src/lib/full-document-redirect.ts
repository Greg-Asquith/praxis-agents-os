// apps/web/src/lib/full-document-redirect.ts

import { redirect } from "@tanstack/react-router"

export function fullDocumentRedirect(path: string): never {
  redirect({
    href: new URL(path, window.location.origin).href,
    reloadDocument: true,
    replace: true,
    throw: true,
  })
  throw new Error("TanStack Router did not throw the full-document redirect.")
}
