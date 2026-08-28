// apps/web/src/features/knowledge/components/integration-import-source-picker.tsx

import { useEffect, useMemo, useRef, useState, type SyntheticEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronRightIcon, SearchIcon } from "lucide-react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { integrationResourcesForConnectionQueryOptions } from "@/features/integrations/api/list-resources"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { usePreviewIntegrationSourceMutation } from "@/features/knowledge/api/preview-integration-source"
import {
  useIntegrationSourceSearchQuery,
  type SearchIntegrationSourcesRequest,
} from "@/features/knowledge/api/search-integration-sources"
import {
  availableKnowledgeSourceResources,
  integrationImportErrorMessage,
  integrationImportResourceState,
  validateIntegrationImportForm,
} from "@/features/knowledge/components/integration-import-form-model"
import type { IntegrationImportPreviewSelection } from "@/features/knowledge/components/integration-import-workflow"
import type {
  KbIntegrationSourceReference,
  KbIntegrationSourceSearchResult,
} from "@/features/knowledge/types"
import { getErrorMessage } from "@/lib/api/errors"
import type { FormValidationEntry } from "@/lib/forms"

type SourceMode = "search" | "url"

export function IntegrationImportSourcePicker({
  connections,
  errorTitle,
  isPrivate,
  onPendingChange,
  onPreviewLoaded,
  open,
  provider,
}: {
  connections: IntegrationConnection[]
  errorTitle: string
  isPrivate: boolean
  onPendingChange: (pending: boolean) => void
  onPreviewLoaded: (selection: IntegrationImportPreviewSelection) => void
  open: boolean
  provider: IntegrationProvider
}) {
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? "")
  const resourcesQuery = useQuery({
    ...integrationResourcesForConnectionQueryOptions(connectionId),
    enabled: open && Boolean(connectionId),
  })
  const resources = useMemo(
    () =>
      availableKnowledgeSourceResources(
        resourcesQuery.data ?? [],
        provider.knowledge_source_resource_types
      ),
    [provider.knowledge_source_resource_types, resourcesQuery.data]
  )
  const [resourceId, setResourceId] = useState("")
  const selectedResourceId = resources.some((resource) => resource.id === resourceId)
    ? resourceId
    : (resources[0]?.id ?? "")
  const [sourceMode, setSourceMode] = useState<SourceMode>("search")
  const [query, setQuery] = useState("")
  const [url, setUrl] = useState("")
  const [searchRequest, setSearchRequest] = useState<SearchIntegrationSourcesRequest | null>(null)
  const [validationEntries, setValidationEntries] = useState<FormValidationEntry[]>([])
  const [previewError, setPreviewError] = useState<string | null>(null)
  const searchQuery = useIntegrationSourceSearchQuery(searchRequest)
  const previewMutation = usePreviewIntegrationSourceMutation()
  const isPending = searchQuery.isFetching || previewMutation.isPending
  const requestGenerationRef = useRef(0)
  const searchError = searchQuery.isError
    ? integrationImportErrorMessage(getErrorMessage(searchQuery.error))
    : null

  useEffect(() => {
    onPendingChange(isPending)
    return () => {
      onPendingChange(false)
    }
  }, [isPending, onPendingChange])

  function resetSourceSelection() {
    requestGenerationRef.current += 1
    setSearchRequest(null)
    setValidationEntries([])
    setPreviewError(null)
  }

  function searchPages(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedResourceId) {
      setValidationEntries([
        {
          fieldId: "knowledge-integration-resource",
          label: "Workspace",
          message: "Choose a connected workspace.",
        },
      ])
      return
    }
    setPreviewError(null)
    setValidationEntries([])
    const nextRequest = { integrationResourceId: selectedResourceId, query: query.trim() }
    if (
      searchRequest?.integrationResourceId === nextRequest.integrationResourceId &&
      searchRequest.query.trim() === nextRequest.query
    ) {
      void searchQuery.refetch()
    } else {
      setSearchRequest(nextRequest)
    }
  }

  async function loadPreview(source: string | KbIntegrationSourceReference) {
    const validation = validateIntegrationImportForm({
      integrationResourceId: selectedResourceId,
      isPrivate,
      source,
      title: "",
    })
    if (validation.length > 0) {
      setValidationEntries(validation)
      return
    }
    setPreviewError(null)
    setValidationEntries([])
    const requestResourceId = selectedResourceId
    const requestGeneration = requestGenerationRef.current
    try {
      const preview = await previewMutation.mutateAsync({
        integration_resource_id: requestResourceId,
        source,
      })
      if (requestGenerationRef.current === requestGeneration) {
        onPreviewLoaded({ preview, resourceId: requestResourceId })
      }
    } catch (mutationError) {
      if (requestGenerationRef.current === requestGeneration) {
        setPreviewError(integrationImportErrorMessage(getErrorMessage(mutationError)))
      }
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <FormAlerts
        error={previewError ?? searchError}
        errorTitle={errorTitle}
        validationEntries={validationEntries}
      />

      <section className="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
        <div>
          <h3 className="font-medium">Connection</h3>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Choose the {provider.display_name} workspace that contains the source.
          </p>
        </div>
        <FieldGroup>
          {connections.length > 1 ? (
            <Field>
              <FieldLabel htmlFor="knowledge-integration-connection">Account</FieldLabel>
              <Select
                disabled={isPending}
                value={connectionId}
                onValueChange={(value) => {
                  if (value !== null) {
                    setConnectionId(value)
                    setResourceId("")
                    resetSourceSelection()
                  }
                }}
              >
                <SelectTrigger className="w-full" id="knowledge-integration-connection">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    {connections.map((connection) => (
                      <SelectItem key={connection.id} value={connection.id}>
                        {connection.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          ) : null}

          <ResourceField
            error={resourcesQuery.error}
            isPending={isPending}
            onResourceChange={(value) => {
              setResourceId(value)
              resetSourceSelection()
            }}
            provider={provider}
            resourceState={integrationImportResourceState({
              hasError: resourcesQuery.isError,
              isLoading: resourcesQuery.isPending,
              resourceCount: resources.length,
            })}
            resources={resources}
            selectedResourceId={selectedResourceId}
          />
        </FieldGroup>
      </section>

      {resources.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-3">
          <div>
            <h3 className="font-medium">Source</h3>
            <p className="text-muted-foreground mt-0.5 text-xs">
              Search sources or paste a link from {provider.display_name}.
            </p>
          </div>
          <Tabs
            className="min-w-0"
            value={sourceMode}
            onValueChange={(value) => {
              if (value === "search") {
                setSourceMode("search")
                resetSourceSelection()
              } else if (value === "url") {
                setSourceMode("url")
                resetSourceSelection()
              }
            }}
          >
            <TabsList>
              <TabsTrigger disabled={isPending} value="search">
                Search sources
              </TabsTrigger>
              <TabsTrigger disabled={isPending} value="url">
                Paste a URL
              </TabsTrigger>
            </TabsList>
            <TabsContent className="min-w-0" value="search">
              <form className="mt-3 flex min-w-0 gap-2" onSubmit={searchPages}>
                <Input
                  aria-label={`Search ${provider.display_name}`}
                  className="flex-1"
                  disabled={isPending}
                  maxLength={500}
                  onChange={(event) => {
                    setQuery(event.target.value)
                  }}
                  placeholder="Search page titles"
                  value={query}
                />
                <Button disabled={isPending} type="submit" variant="outline">
                  <SearchIcon data-icon="inline-start" />
                  Search
                </Button>
              </form>
              {searchRequest && searchQuery.data ? (
                <SearchResults
                  isPending={isPending}
                  onSelect={loadPreview}
                  results={searchQuery.data}
                />
              ) : null}
            </TabsContent>
            <TabsContent className="min-w-0" value="url">
              <form
                className="mt-3 min-w-0"
                onSubmit={(event) => {
                  event.preventDefault()
                  void loadPreview(url)
                }}
              >
                <Field>
                  <FieldLabel htmlFor="knowledge-integration-url">URL</FieldLabel>
                  <div className="flex min-w-0 gap-2">
                    <Input
                      autoComplete="url"
                      className="flex-1"
                      disabled={isPending}
                      id="knowledge-integration-url"
                      onChange={(event) => {
                        setUrl(event.target.value)
                      }}
                      placeholder="Paste a URL"
                      type="url"
                      value={url}
                    />
                    <Button disabled={isPending} type="submit" variant="outline">
                      Preview
                    </Button>
                  </div>
                </Field>
              </form>
            </TabsContent>
          </Tabs>
        </section>
      ) : null}
    </div>
  )
}

function SearchResults({
  isPending,
  onSelect,
  results,
}: {
  isPending: boolean
  onSelect: (source: KbIntegrationSourceReference) => Promise<void>
  results: KbIntegrationSourceSearchResult[]
}) {
  if (results.length === 0) {
    return (
      <p className="text-muted-foreground mt-3 rounded-lg border px-3 py-6 text-center text-sm">
        No sources match this search. Try another title or paste the URL.
      </p>
    )
  }
  return (
    <div className="mt-3 max-h-56 min-w-0 divide-y overflow-y-auto rounded-lg border">
      {results.map((result) => (
        <button
          className="hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:ring-ring/50 group flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-3 text-left outline-none first:rounded-t-lg last:rounded-b-lg focus-visible:ring-3"
          disabled={isPending}
          key={`${result.url}:${result.title}`}
          onClick={() => void onSelect(result.reference)}
          type="button"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{result.title}</span>
            <span className="text-muted-foreground mt-0.5 block truncate text-xs">
              {result.url}
            </span>
          </span>
          <span className="text-muted-foreground group-hover:text-foreground flex shrink-0 items-center gap-1 text-xs font-medium">
            Preview
            <ChevronRightIcon className="size-3.5" />
          </span>
        </button>
      ))}
    </div>
  )
}

function ResourceField({
  error,
  isPending,
  onResourceChange,
  provider,
  resources,
  resourceState,
  selectedResourceId,
}: {
  error: Error | null
  isPending: boolean
  onResourceChange: (value: string) => void
  provider: IntegrationProvider
  resources: ReturnType<typeof availableKnowledgeSourceResources>
  resourceState: ReturnType<typeof integrationImportResourceState>
  selectedResourceId: string
}) {
  if (resourceState === "loading") {
    return (
      <div className="flex flex-col gap-2" aria-label="Loading connected workspaces">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-8 w-full" />
      </div>
    )
  }
  if (resourceState === "error") {
    return (
      <Alert variant="destructive">
        <AlertTitle>Connected workspaces unavailable</AlertTitle>
        <AlertDescription>{integrationImportErrorMessage(getErrorMessage(error))}</AlertDescription>
      </Alert>
    )
  }
  if (resourceState === "empty") {
    return (
      <Alert>
        <AlertTitle>No available workspace</AlertTitle>
        <AlertDescription>
          Reconnect {provider.display_name} or wait for resource discovery to finish, then try
          again.
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <Field>
      <FieldLabel htmlFor="knowledge-integration-resource">
        {provider.display_name} workspace
      </FieldLabel>
      <Select
        disabled={isPending}
        value={selectedResourceId}
        onValueChange={(value) => {
          if (value !== null) {
            onResourceChange(value)
          }
        }}
      >
        <SelectTrigger className="w-full" id="knowledge-integration-resource">
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="start">
          <SelectGroup>
            {resources.map((resource) => (
              <SelectItem key={resource.id} value={resource.id}>
                {resource.display_name}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}
