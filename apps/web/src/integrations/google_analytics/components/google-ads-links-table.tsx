// apps/web/src/integrations/google_analytics/components/google-ads-links-table.tsx

import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatDateTime, formatGoogleAdsAccountId } from "@/lib/format"

export type GoogleAdsLink = {
  adsPersonalizationEnabled: boolean
  canManageClients: boolean
  createdAt: string | null
  customerId: string
}

export function GoogleAnalyticsGoogleAdsLinksTable({ links }: { links: GoogleAdsLink[] }) {
  return (
    <div className="min-w-0 overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Google Ads account</TableHead>
            <TableHead>Access</TableHead>
            <TableHead>Ads personalization</TableHead>
            <TableHead>Linked</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {links.map((link) => (
            <TableRow key={link.customerId}>
              <TableCell className="font-mono">
                {formatGoogleAdsAccountId(link.customerId)}
              </TableCell>
              <TableCell>
                {link.canManageClients ? <Badge variant="secondary">Manager</Badge> : "Direct"}
              </TableCell>
              <TableCell>
                <Badge variant={link.adsPersonalizationEnabled ? "success" : "outline"}>
                  {link.adsPersonalizationEnabled ? "Enabled" : "Disabled"}
                </Badge>
              </TableCell>
              <TableCell>
                {link.createdAt ? (
                  <time dateTime={link.createdAt}>{formatDateTime(link.createdAt)}</time>
                ) : (
                  <span className="text-muted-foreground">Not available</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-muted-foreground pt-2 text-xs">
        {String(links.length)} linked {links.length === 1 ? "account" : "accounts"}
      </p>
    </div>
  )
}
