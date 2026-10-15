// apps/web/src/integrations/meta_ads/components/object-card.tsx

export function MetaAdsManagerLink({ href }: { href: string }) {
  return (
    <a
      className="text-primary w-fit text-sm underline-offset-2 hover:underline"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      Open in Ads Manager
    </a>
  )
}
