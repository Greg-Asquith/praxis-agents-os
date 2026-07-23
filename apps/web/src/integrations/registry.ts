// apps/web/src/integrations/registry.ts

import { useEffect, useSyncExternalStore, type ComponentType, type SVGProps } from "react"

import type { IntegrationUiModule, ToolRowPresenter } from "@/integrations/contract"

type IntegrationUiModuleImport = { default: IntegrationUiModule }
type IntegrationUiModuleLoader = () => Promise<IntegrationUiModuleImport>

const MODULE_LOADERS: Record<string, IntegrationUiModuleLoader> = {
  airtable: () => import("@/integrations/airtable"),
  gmail: () => import("@/integrations/gmail"),
  google_ads: () => import("@/integrations/google_ads"),
}
const loadedModules = new Map<string, IntegrationUiModule>()
const loadingModules = new Map<string, Promise<IntegrationUiModule | null>>()
const listeners = new Set<() => void>()

export async function loadIntegrationUiModules(providerKeys: readonly string[]) {
  await Promise.all(providerKeys.map(loadIntegrationUiModule))
}

// Integration tools are namespaced "<provider>_<tool>", so rows can resolve
// their provider before (or without) the tool presentations query.
export function providerKeyForToolName(toolName: string): string | null {
  for (const providerKey of Object.keys(MODULE_LOADERS)) {
    if (toolName.startsWith(`${providerKey}_`)) {
      return providerKey
    }
  }
  return null
}

export function integrationToolRowPresenters(providerKey: string | null): ToolRowPresenter[] {
  if (!providerKey) {
    return []
  }
  return loadedModules.get(providerKey)?.toolRowPresenters ?? []
}

export function integrationIcon(token: string): ComponentType<SVGProps<SVGSVGElement>> | null {
  for (const module of loadedModules.values()) {
    const icon = module.icons?.[token]
    if (icon) {
      return icon
    }
  }
  return null
}

export function useIntegrationUiModule(providerKey: string | null) {
  useEffect(() => {
    if (providerKey) {
      void loadIntegrationUiModule(providerKey)
    }
  }, [providerKey])

  return useSyncExternalStore(
    subscribe,
    () => (providerKey ? (loadedModules.get(providerKey) ?? null) : null),
    () => null
  )
}

async function loadIntegrationUiModule(providerKey: string) {
  const loaded = loadedModules.get(providerKey)
  if (loaded) {
    return loaded
  }
  const pending = loadingModules.get(providerKey)
  if (pending) {
    return pending
  }
  const loader = MODULE_LOADERS[providerKey]
  if (!loader) {
    return null
  }
  const promise = loader()
    .then(({ default: module }) => {
      if (module.providerKey !== providerKey) {
        throw new Error(`Integration UI module '${providerKey}' declared '${module.providerKey}'.`)
      }
      loadedModules.set(providerKey, module)
      for (const listener of listeners) {
        listener()
      }
      return module
    })
    .catch(() => null)
    .finally(() => {
      loadingModules.delete(providerKey)
    })
  loadingModules.set(providerKey, promise)
  return promise
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
