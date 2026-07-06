// apps/web/src/features/conversations/components/tool-ui-icon.tsx

import {
  BookOpenIcon,
  BotIcon,
  FileIcon,
  FilePlus2Icon,
  FilesIcon,
  GlobeIcon,
  ImageIcon,
  LinkIcon,
  ListTodoIcon,
  SearchIcon,
  SparklesIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react"

const TOOL_UI_ICONS: Record<string, LucideIcon> = {
  book: BookOpenIcon,
  bot: BotIcon,
  file: FileIcon,
  "file-plus": FilePlus2Icon,
  files: FilesIcon,
  globe: GlobeIcon,
  image: ImageIcon,
  link: LinkIcon,
  "list-todo": ListTodoIcon,
  search: SearchIcon,
  sparkles: SparklesIcon,
  tool: WrenchIcon,
}

export function ToolUiIcon({ token }: { token: string | null }) {
  if (!token || token === "tool") {
    return null
  }
  const Icon = TOOL_UI_ICONS[token]
  if (!Icon) {
    return null
  }
  return <Icon className="text-muted-foreground size-3.5 shrink-0" />
}
