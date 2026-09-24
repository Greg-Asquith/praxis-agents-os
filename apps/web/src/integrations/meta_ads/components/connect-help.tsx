// apps/web/src/integrations/meta_ads/components/connect-help.tsx

import { KeyRoundIcon, Share2Icon, ShieldCheckIcon } from "lucide-react"

import { ConnectHelpCards } from "@/integrations/connect-help"

export function MetaAdsConnectHelp() {
  return (
    <ConnectHelpCards
      items={[
        {
          body: "Ask each client to add your agency's business portfolio as a partner on their ad account and Page.",
          icon: Share2Icon,
          title: "Share client accounts with your agency",
        },
        {
          body: "In Business Settings > Users > System users, assign Manage campaigns on each ad account, or View performance for reporting only. Assign Advertise on each Page.",
          icon: ShieldCheckIcon,
          title: "Assign them to your system user",
        },
        {
          body: (
            <>
              Choose your agency&apos;s Meta app, set expiry to Never, and select ads_read,
              ads_management, business_management, pages_show_list, pages_manage_ads, and
              pages_read_engagement. Use a System User token, not a personal user token. After
              assigning more accounts, click <strong>Look for New Resources</strong> without
              replacing the token. To revoke it, use Business Settings &gt; Users &gt; System users
              in Meta.
            </>
          ),
          icon: KeyRoundIcon,
          title: "Generate the token",
        },
      ]}
    />
  )
}
