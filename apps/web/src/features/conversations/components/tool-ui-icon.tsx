// apps/web/src/features/conversations/components/tool-ui-icon.tsx

import { createElement } from "react"
import {
  BookOpenIcon,
  BarChart3Icon,
  BotIcon,
  CodeIcon,
  FileIcon,
  FilePlus2Icon,
  FilesIcon,
  GlobeIcon,
  ImageIcon,
  LinkIcon,
  ListTodoIcon,
  MailIcon,
  SearchIcon,
  SparklesIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react"

import { integrationIcon } from "@/integrations/registry"

const TOOL_UI_ICONS: Record<string, LucideIcon> = {
  chart: BarChart3Icon,
  book: BookOpenIcon,
  bot: BotIcon,
  code: CodeIcon,
  file: FileIcon,
  "file-plus": FilePlus2Icon,
  files: FilesIcon,
  globe: GlobeIcon,
  image: ImageIcon,
  link: LinkIcon,
  "list-todo": ListTodoIcon,
  mail: MailIcon,
  search: SearchIcon,
  sparkles: SparklesIcon,
  tool: WrenchIcon,
}

export function ToolUiIcon({ token }: { token: string | null }) {
  if (!token || token === "tool") {
    return null
  }
  const Icon = integrationIcon(token) ?? TOOL_UI_ICONS[token]
  if (!Icon) {
    return null
  }
  return createElement(Icon, { className: "text-muted-foreground size-3.5 shrink-0" })
}
