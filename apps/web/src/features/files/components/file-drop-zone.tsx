// apps/web/src/features/files/components/file-drop-zone.tsx

import { useRef, useState, type DragEvent, type ReactNode } from "react"

import { FileUploadStatus } from "@/features/files/components/file-upload-status"
import type { FileUpload } from "@/features/files/components/use-file-upload"
import { cn } from "@/lib/utils"

export function FileDropZone({
  children,
  className,
  upload,
}: {
  children: ReactNode
  className?: string
  upload: FileUpload
}) {
  const { isUploading, uploadFiles } = upload
  const [isDragging, setIsDragging] = useState(false)
  // Nested elements fire enter and leave in pairs, so the depth tells when the pointer really left.
  const dragDepth = useRef(0)

  function carriesFiles(event: DragEvent<HTMLDivElement>) {
    return Array.from(event.dataTransfer.types).includes("Files")
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    if (!carriesFiles(event)) return
    event.preventDefault()
    dragDepth.current += 1
    setIsDragging(true)
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!carriesFiles(event)) return
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setIsDragging(false)
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (!carriesFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = isUploading ? "none" : "copy"
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    if (!carriesFiles(event)) return
    event.preventDefault()
    dragDepth.current = 0
    setIsDragging(false)
    void uploadFiles(event.dataTransfer.files)
  }

  return (
    <div
      className={cn("relative flex min-w-0 flex-col gap-6", className)}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <FileUploadStatus upload={upload} />
      {children}
      {isDragging ? (
        <div
          aria-hidden="true"
          className="bg-background/80 border-primary text-primary pointer-events-none absolute -inset-3 z-10 flex items-center justify-center rounded-xl border-2 border-dashed text-sm font-medium"
        >
          Drop files to upload
        </div>
      ) : null}
    </div>
  )
}
