// apps/web/src/integrations/sharepoint/components/link-failure.tsx

import type { FanOutEntry } from "@/components/tool-ui/fan-out"
import { nodeText } from "@/components/tool-ui/untrusted-node"
import { isRecord } from "@/lib/guards"

export function SharePointLinkFailure({ entry }: { entry: FanOutEntry }) {
  const library =
    entry.errorCode === "library_not_selected" && isRecord(entry.data)
      ? nodeText(entry.data["library"])
      : null
  return (
    <div className="grid min-w-0 gap-2 wrap-break-word">
      {library ? <p className="text-sm">Library: {library}</p> : null}
      <p className="text-destructive text-sm">
        {entry.errorMessage ?? "This connection did not return a result."}
      </p>
    </div>
  )
}
