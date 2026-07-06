// apps/web/src/components/confirm-dialog.tsx

import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

type ConfirmDialogVariant = "default" | "destructive"

type ConfirmDialogProps = {
  confirmIcon?: ReactNode
  confirmLabel: string
  confirmPendingLabel?: string
  description: ReactNode
  isPending?: boolean
  onConfirm: () => void | Promise<void>
  onOpenChange: (open: boolean) => void
  open: boolean
  title: string
  variant?: ConfirmDialogVariant
}

export function ConfirmDialog({
  confirmIcon,
  confirmLabel,
  confirmPendingLabel,
  description,
  isPending = false,
  onConfirm,
  onOpenChange,
  open,
  title,
  variant = "destructive",
}: ConfirmDialogProps) {
  function handleOpenChange(nextOpen: boolean) {
    if (isPending && !nextOpen) {
      return
    }
    onOpenChange(nextOpen)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button disabled={isPending} variant="outline" />}>
            Cancel
          </DialogClose>
          <Button
            disabled={isPending}
            onClick={() => {
              void onConfirm()
            }}
            type="button"
            variant={variant}
          >
            {confirmIcon}
            {isPending && confirmPendingLabel ? confirmPendingLabel : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
