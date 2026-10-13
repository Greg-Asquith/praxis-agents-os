// apps/web/src/features/files/components/file-upload-status.tsx

import { useEffect, type ReactNode } from "react"
import { CircleAlertIcon, CircleCheckIcon, Loader2Icon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import type { FileUpload } from "@/features/files/components/use-file-upload"
import { formatBytes } from "@/lib/format"

const NOTICE_DISMISS_MS = 5_000

export function FileUploadStatus({ upload }: { upload: FileUpload }) {
  const { cancel, dismiss, error, message, progress } = upload

  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(dismiss, NOTICE_DISMISS_MS)
    return () => {
      window.clearTimeout(timer)
    }
  }, [dismiss, message])

  if (progress) {
    const { fileCount, fileName, fileNumber, loadedBytes, totalBytes } = progress
    const percent =
      loadedBytes === null || totalBytes === 0
        ? null
        : Math.min(100, Math.floor((loadedBytes / totalBytes) * 100))
    const transfer =
      loadedBytes === null
        ? "Uploading"
        : percent === 100
          ? "Finishing"
          : `${formatBytes(loadedBytes)} of ${formatBytes(totalBytes)} · ${String(percent)}%`
    return (
      <UploadPanel
        action={
          loadedBytes === null ? null : (
            <Button onClick={cancel} size="sm" type="button" variant="ghost">
              Cancel
            </Button>
          )
        }
        icon={
          <Loader2Icon className="text-muted-foreground size-4 animate-spin motion-reduce:animate-none" />
        }
        title={
          fileCount > 1
            ? `Uploading ${String(fileNumber)} of ${String(fileCount)}`
            : "Uploading 1 File"
        }
      >
        <p className="truncate text-sm">{fileName}</p>
        <Progress aria-label={`Uploading ${fileName}`} className="mt-2" value={percent} />
        <p className="text-muted-foreground mt-1.5 text-xs tabular-nums">{transfer}</p>
      </UploadPanel>
    )
  }
  if (error) {
    return (
      <UploadPanel
        action={<DismissButton onClick={dismiss} />}
        icon={<CircleAlertIcon className="text-destructive size-4" />}
        title="Upload Failed"
      >
        <p className="text-muted-foreground text-sm wrap-anywhere">{error}</p>
      </UploadPanel>
    )
  }
  if (message) {
    return (
      <UploadPanel
        action={<DismissButton onClick={dismiss} />}
        icon={<CircleCheckIcon className="text-primary size-4" />}
        title={message}
      />
    )
  }
  return null
}

function UploadPanel({
  action,
  children,
  icon,
  title,
}: {
  action: ReactNode
  children?: ReactNode
  icon: ReactNode
  title: string
}) {
  return (
    <div
      aria-live="polite"
      className="bg-popover text-popover-foreground animate-in fade-in-0 slide-in-from-bottom-2 fixed right-4 bottom-4 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-xl border p-3 shadow-lg"
      role="status"
    >
      <div className="flex items-center gap-2">
        <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
        <p className="min-w-0 flex-1 truncate text-sm font-medium">{title}</p>
        {action}
      </div>
      {children ? <div className="mt-2 pl-6">{children}</div> : null}
    </div>
  )
}

function DismissButton({ onClick }: { onClick: () => void }) {
  return (
    <Button aria-label="Dismiss" onClick={onClick} size="icon-sm" type="button" variant="ghost">
      <XIcon />
    </Button>
  )
}
