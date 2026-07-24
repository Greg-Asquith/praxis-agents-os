// apps/web/src/features/knowledge/components/add-document-menu.tsx

import { useState } from "react"
import { FileUpIcon, LinkIcon, PlusIcon, SquarePenIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { DocumentUploadButton } from "@/features/knowledge/components/document-upload-button"
import { ManualDocumentForm } from "@/features/knowledge/components/manual-document-form"
import { UrlDocumentForm } from "@/features/knowledge/components/url-document-form"

type AddMode = "manual" | "url" | "upload"

const DIALOG_COPY: Record<AddMode, { title: string; description: string }> = {
  manual: {
    title: "Write a Knowledge Base Document",
    description: "Add durable Markdown content that agents can search and cite.",
  },
  url: {
    title: "Add to Knowledge Base from a URL",
    description: "Praxis will fetch the public page and prepare its readable content.",
  },
  upload: {
    title: "Upload to Knowledge Base",
    description: "Upload a document through Files, then add it to the Knowledge Base.",
  },
}

export function AddDocumentMenu() {
  const [mode, setMode] = useState<AddMode | null>(null)
  const copy = mode ? DIALOG_COPY[mode] : null

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button />}>
          <PlusIcon data-icon="inline-start" />
          Add Document
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onClick={() => {
              setMode("manual")
            }}
          >
            <SquarePenIcon />
            Write Manually
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              setMode("url")
            }}
          >
            <LinkIcon />
            Add from URL
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              setMode("upload")
            }}
          >
            <FileUpIcon />
            Upload Document
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={mode !== null}
        onOpenChange={(open) => {
          if (!open) {
            setMode(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          {copy ? (
            <DialogHeader>
              <DialogTitle>{copy.title}</DialogTitle>
              <DialogDescription>{copy.description}</DialogDescription>
            </DialogHeader>
          ) : null}
          {mode === "manual" ? (
            <ManualDocumentForm
              onSaved={() => {
                setMode(null)
              }}
            />
          ) : null}
          {mode === "url" ? (
            <UrlDocumentForm
              onSaved={() => {
                setMode(null)
              }}
            />
          ) : null}
          {mode === "upload" ? (
            <DocumentUploadButton
              onSaved={() => {
                setMode(null)
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}
