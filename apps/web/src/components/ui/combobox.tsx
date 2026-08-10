// apps/web/src/components/ui/combobox.tsx

import { Combobox as ComboboxPrimitive } from "@base-ui/react/combobox"
import { CheckIcon, ChevronDownIcon, XIcon } from "lucide-react"

import { cn } from "@/lib/utils"

const Combobox = ComboboxPrimitive.Root

function ComboboxInputGroup({ className, ...props }: ComboboxPrimitive.InputGroup.Props) {
  return (
    <ComboboxPrimitive.InputGroup
      className={cn(
        "border-input focus-within:border-ring focus-within:ring-ring/50 flex min-h-8 w-full items-center gap-1 rounded-lg border bg-transparent px-2.5 text-sm focus-within:ring-3",
        className
      )}
      data-slot="combobox-input-group"
      {...props}
    />
  )
}

function ComboboxInput({ className, ...props }: ComboboxPrimitive.Input.Props) {
  return (
    <ComboboxPrimitive.Input
      className={cn(
        "placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent py-1.5 outline-none disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      data-slot="combobox-input"
      {...props}
    />
  )
}

function ComboboxTrigger({ className, ...props }: ComboboxPrimitive.Trigger.Props) {
  return (
    <ComboboxPrimitive.Trigger
      className={cn(
        "text-muted-foreground hover:text-foreground flex size-6 shrink-0 items-center justify-center rounded-md outline-none focus-visible:ring-2",
        className
      )}
      data-slot="combobox-trigger"
      {...props}
    >
      <ChevronDownIcon className="size-4" />
    </ComboboxPrimitive.Trigger>
  )
}

function ComboboxContent({ className, children, ...props }: ComboboxPrimitive.Popup.Props) {
  return (
    <ComboboxPrimitive.Portal>
      <ComboboxPrimitive.Positioner align="start" className="isolate z-50" sideOffset={4}>
        <ComboboxPrimitive.Popup
          className={cn(
            "bg-popover text-popover-foreground ring-border max-h-72 w-(--anchor-width) min-w-64 overflow-y-auto rounded-lg p-1.5 shadow-md ring-1 outline-none",
            className
          )}
          data-slot="combobox-content"
          {...props}
        >
          <ComboboxPrimitive.List>{children}</ComboboxPrimitive.List>
        </ComboboxPrimitive.Popup>
      </ComboboxPrimitive.Positioner>
    </ComboboxPrimitive.Portal>
  )
}

function ComboboxItem({ className, children, ...props }: ComboboxPrimitive.Item.Props) {
  return (
    <ComboboxPrimitive.Item
      className={cn(
        "data-highlighted:bg-accent data-highlighted:text-accent-foreground relative flex cursor-default items-start gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-disabled:pointer-events-none data-disabled:opacity-50",
        className
      )}
      data-slot="combobox-item"
      {...props}
    >
      <span className="min-w-0 flex-1">{children}</span>
      <ComboboxPrimitive.ItemIndicator className="mt-0.5 shrink-0">
        <CheckIcon className="size-4" />
      </ComboboxPrimitive.ItemIndicator>
    </ComboboxPrimitive.Item>
  )
}

function ComboboxEmpty({ className, ...props }: ComboboxPrimitive.Empty.Props) {
  return (
    <ComboboxPrimitive.Empty
      className={cn("text-muted-foreground px-2.5 py-5 text-center text-sm", className)}
      data-slot="combobox-empty"
      {...props}
    />
  )
}

function ComboboxChips({ className, ...props }: ComboboxPrimitive.Chips.Props) {
  return (
    <ComboboxPrimitive.Chips
      className={cn("flex min-w-0 flex-1 flex-wrap items-center gap-1.5", className)}
      data-slot="combobox-chips"
      {...props}
    />
  )
}

function ComboboxChip({ className, ...props }: ComboboxPrimitive.Chip.Props) {
  return (
    <ComboboxPrimitive.Chip
      className={cn(
        "bg-muted text-foreground inline-flex max-w-full items-center gap-1 rounded-md px-2 py-1 text-xs",
        className
      )}
      data-slot="combobox-chip"
      {...props}
    />
  )
}

function ComboboxChipRemove({ className, ...props }: ComboboxPrimitive.ChipRemove.Props) {
  return (
    <ComboboxPrimitive.ChipRemove
      className={cn("text-muted-foreground hover:text-foreground shrink-0", className)}
      data-slot="combobox-chip-remove"
      {...props}
    >
      <XIcon className="size-3" />
    </ComboboxPrimitive.ChipRemove>
  )
}

export {
  Combobox,
  ComboboxChip,
  ComboboxChipRemove,
  ComboboxChips,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxInputGroup,
  ComboboxItem,
  ComboboxTrigger,
}
