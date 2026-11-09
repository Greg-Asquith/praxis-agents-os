// apps/web/src/integrations/google_ads/components/ad-copy-editor.tsx

import { TextField } from "@/integrations/ads/components/controls"
import { SearchAdPreview } from "@/integrations/google_ads/components/search-ad-preview"
import { TextAssetList } from "@/integrations/google_ads/components/text-asset-list"
import {
  DESCRIPTION_LIMITS,
  DESCRIPTION_PINS,
  HEADLINE_LIMITS,
  HEADLINE_PINS,
  type AdCopy,
} from "@/integrations/google_ads/lib/create-ads"

/** Edits a responsive search ad's copy and links, with its search result preview above. */
export function AdCopyEditor({
  ad,
  disabled,
  onEdit,
}: {
  ad: AdCopy
  disabled: boolean
  onEdit: (patch: Partial<AdCopy>) => void
}) {
  return (
    <>
      <SearchAdPreview ad={ad} />
      <TextAssetList
        assets={ad.headlines}
        disabled={disabled}
        limits={HEADLINE_LIMITS}
        noun="Headline"
        onChange={(headlines) => {
          onEdit({ headlines })
        }}
        pins={HEADLINE_PINS}
      />
      <TextAssetList
        assets={ad.descriptions}
        disabled={disabled}
        limits={DESCRIPTION_LIMITS}
        noun="Description"
        onChange={(descriptions) => {
          onEdit({ descriptions })
        }}
        pins={DESCRIPTION_PINS}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          disabled={disabled}
          label="Final URL"
          onChange={(finalUrl) => {
            onEdit({ finalUrl })
          }}
          value={ad.finalUrl}
        />
        <TextField
          disabled={disabled}
          label="Mobile URL (Optional)"
          onChange={(mobileFinalUrl) => {
            onEdit({ mobileFinalUrl })
          }}
          value={ad.mobileFinalUrl}
        />
        <TextField
          disabled={disabled}
          label="Path 1"
          onChange={(path1) => {
            onEdit({ path1 })
          }}
          value={ad.path1}
        />
        <TextField
          disabled={disabled}
          label="Path 2"
          onChange={(path2) => {
            onEdit({ path2 })
          }}
          value={ad.path2}
        />
      </div>
    </>
  )
}
