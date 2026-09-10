// apps/web/src/features/usage/components/model-pricing-dialog.tsx

import { useState } from "react"
import { InfoIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useModelPricingQuery } from "@/features/usage/api/get-model-pricing"
import { formatUsd } from "@/features/usage/format"
import type { ModelPricing } from "@/features/usage/types"

export function ModelPricingDialog() {
  const [open, setOpen] = useState(false)
  const query = useModelPricingQuery(open)

  return (
    <Dialog open={open} onOpenChange={setOpen} disablePointerDismissal>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <InfoIcon data-icon="inline-start" />
        Model pricing
      </DialogTrigger>
      <DialogContent className="flex h-[min(52rem,calc(100dvh-2rem))] min-h-0 flex-col gap-4 overflow-hidden sm:max-w-6xl">
        <DialogHeader className="shrink-0 pr-8">
          <DialogTitle>Model pricing</DialogTitle>
          <DialogDescription>
            USD per million tokens. These rates estimate your AI usage costs.
          </DialogDescription>
        </DialogHeader>
        {query.isPending ? (
          <p role="status" className="text-muted-foreground py-4">
            Loading model pricing…
          </p>
        ) : query.isError ? (
          <div className="flex items-center justify-between gap-3" role="alert">
            <p>Model pricing could not load.</p>
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <>
            <p className="text-muted-foreground text-xs">
              Rates effective on {query.data.as_of} (UTC).
            </p>
            <ModelPricingTable pricing={query.data} />
          </>
        )}
        <p className="text-muted-foreground shrink-0 text-xs">
          Past usage uses the rate effective on its usage date. Cache reads reuse saved input; cache
          writes save input for reuse. Image output charges and provider-specific extras are
          excluded from this table. Models without a known rate remain unpriced.
        </p>
      </DialogContent>
    </Dialog>
  )
}

function ModelPricingTable({ pricing }: { pricing: ModelPricing }) {
  return (
    <div className="min-h-0 flex-1 overflow-hidden rounded-md border [&>[data-slot=table-container]]:h-full [&>[data-slot=table-container]]:overflow-auto">
      <Table className="min-w-[44rem]" aria-label="Model token rates in USD per million tokens">
        <TableHeader className="bg-popover sticky top-0">
          <TableRow>
            <TableHead>Model</TableHead>
            <TableHead className="text-right">Input</TableHead>
            <TableHead className="text-right">Cache read</TableHead>
            <TableHead className="text-right">Cache write</TableHead>
            <TableHead className="text-right">Output</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pricing.models.map((price) => (
            <TableRow key={`${price.provider}:${price.model}`}>
              <TableCell>
                <span className="font-medium">{price.model}</span>
                <span className="text-muted-foreground block text-xs">{price.provider}</span>
              </TableCell>
              <TableCell className="text-right">{formatUsd(price.input_usd_per_mtok)}</TableCell>
              <TableCell className="text-right">
                {formatUsd(price.cache_read_usd_per_mtok)}
              </TableCell>
              <TableCell className="text-right">
                {formatUsd(price.cache_write_usd_per_mtok)}
              </TableCell>
              <TableCell className="text-right">{formatUsd(price.output_usd_per_mtok)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
