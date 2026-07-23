// apps/web/src/integrations/google_ads/account-hierachy.tsx

import { Badge } from "@/components/ui/badge"
import { formatGoogleAdsAccountId, titleCaseToken } from "@/lib/format"

export type GoogleAdsAccount = {
  currencyCode: string
  customerId: string
  displayName: string
  enabled: boolean
  manager: boolean
  parentCustomerId: string | null
  status: string
  writable: boolean
}

export function GoogleAdsAccountHierarchy({ accounts }: { accounts: GoogleAdsAccount[] }) {
  return (
    <div className="grid min-w-0 gap-1" role="list">
      {accounts.map((account) => (
        <div
          className="hover:bg-muted/30 flex min-w-0 flex-wrap items-center gap-2 rounded-md px-2 py-2"
          key={account.customerId}
          role="listitem"
          style={{
            paddingInlineStart: `${String(
              8 + Math.min(accountDepth(account, accounts), 6) * 20
            )}px`,
          }}
        >
          <span className="min-w-40 flex-1">
            <span className="block truncate text-sm font-medium">
              {formatGoogleAdsAccountId(account.displayName)}
            </span>
            <code className="text-muted-foreground text-xs">
              {formatGoogleAdsAccountId(account.customerId)}
            </code>
          </span>
          {account.manager ? <Badge variant="secondary">Manager</Badge> : null}
          <Badge variant={statusVariant(account.status)}>
            {titleCaseToken(account.status, account.status || "Unknown")}
          </Badge>
          <Badge variant={account.writable ? "success" : "outline"}>
            {account.writable ? "Writable" : "Read only"}
          </Badge>
          {account.currencyCode ? <Badge variant="outline">{account.currencyCode}</Badge> : null}
          {!account.enabled ? <Badge variant="warning">Not selected</Badge> : null}
        </div>
      ))}
    </div>
  )
}

function accountDepth(account: GoogleAdsAccount, accounts: GoogleAdsAccount[]): number {
  const parents = new Map(accounts.map((item) => [item.customerId, item.parentCustomerId]))
  const visited = new Set([account.customerId])
  let parentId = account.parentCustomerId
  let depth = 0
  while (parentId && !visited.has(parentId) && depth < accounts.length) {
    visited.add(parentId)
    depth += 1
    parentId = parents.get(parentId) ?? null
  }
  return depth
}

function statusVariant(status: string): "success" | "warning" | "destructive" | "outline" {
  const normalized = status.toLowerCase()
  if (normalized === "enabled" || normalized === "active") {
    return "success"
  }
  if (normalized === "paused" || normalized === "pending") {
    return "warning"
  }
  if (normalized === "removed" || normalized === "failed") {
    return "destructive"
  }
  return "outline"
}
