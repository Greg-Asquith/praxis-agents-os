// apps/web/src/features/knowledge/components/add-document-menu.tsx

import { useMemo, useState } from "react"
import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { FileUpIcon, LinkIcon, PlusIcon, RefreshCwIcon, SquarePenIcon } from "lucide-react"

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
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { integrationConnectionsQueryOptions } from "@/features/integrations/api/list-connections"
import { integrationProvidersQueryOptions } from "@/features/integrations/api/list-providers"
import { ProviderMark } from "@/features/integrations/components/provider-mark"
import { DocumentUploadButton } from "@/features/knowledge/components/document-upload-button"
import { IntegrationImportDialog } from "@/features/knowledge/components/integration-import-dialog"
import {
  eligibleKnowledgeSourceProviders,
  type KnowledgeSourceProviderOption,
} from "@/features/knowledge/components/integration-import-form-model"
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
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const providersQuery = useQuery(integrationProvidersQueryOptions())
  const connectionsQuery = useQuery(integrationConnectionsQueryOptions())
  const [mode, setMode] = useState<AddMode | null>(null)
  const [integrationOption, setIntegrationOption] = useState<KnowledgeSourceProviderOption | null>(
    null
  )
  const integrationOptions = useMemo(
    () =>
      eligibleKnowledgeSourceProviders(
        providersQuery.data ?? [],
        connectionsQuery.data?.items ?? [],
        user.id
      ),
    [connectionsQuery.data?.items, providersQuery.data, user.id]
  )
  const integrationCatalogError = providersQuery.isError || connectionsQuery.isError
  const integrationCatalogLoading =
    !integrationCatalogError &&
    integrationOptions.length === 0 &&
    (providersQuery.isPending || connectionsQuery.isPending)
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
          {integrationOptions.map((option) => (
            <DropdownMenuItem
              key={option.provider.provider_key}
              onClick={() => {
                setIntegrationOption(option)
              }}
            >
              <ProviderMark providerKey={option.provider.provider_key} />
              Import from {option.provider.display_name}
            </DropdownMenuItem>
          ))}
          {integrationCatalogLoading || integrationCatalogError ? <DropdownMenuSeparator /> : null}
          {integrationCatalogLoading ? (
            <DropdownMenuLabel>Loading import options…</DropdownMenuLabel>
          ) : null}
          {integrationCatalogError ? (
            <>
              <DropdownMenuLabel className="text-destructive max-w-56 whitespace-normal">
                Import options unavailable.
              </DropdownMenuLabel>
              <DropdownMenuItem
                onClick={() => {
                  void Promise.all([providersQuery.refetch(), connectionsQuery.refetch()])
                }}
              >
                <RefreshCwIcon />
                Try Again
              </DropdownMenuItem>
            </>
          ) : null}
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
      {integrationOption ? (
        <IntegrationImportDialog
          connections={integrationOption.connections}
          key={integrationOption.provider.provider_key}
          onOpenChange={(open) => {
            if (!open) {
              setIntegrationOption(null)
            }
          }}
          open
          provider={integrationOption.provider}
        />
      ) : null}
    </>
  )
}
