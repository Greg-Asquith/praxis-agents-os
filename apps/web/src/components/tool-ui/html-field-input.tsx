// apps/web/src/components/tool-ui/html-field-input.tsx

import { HtmlContentFrame } from "@/components/tool-ui/html-content-frame"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"

export function HtmlFieldInput({
  disabled,
  id,
  label,
  onChange,
  value,
}: {
  disabled: boolean
  id: string
  label: string
  onChange: (value: string) => void
  value: string
}) {
  return (
    <Tabs className="min-w-0 gap-1.5" defaultValue="preview">
      <TabsList className="self-start">
        <TabsTrigger className="text-xs" value="preview">
          Preview
        </TabsTrigger>
        <TabsTrigger className="text-xs" value="edit">
          Edit HTML
        </TabsTrigger>
      </TabsList>
      <TabsContent value="preview">
        <HtmlContentFrame
          className="border-input h-80 rounded-lg border"
          html={value}
          title={label}
        />
      </TabsContent>
      <TabsContent value="edit">
        <Textarea
          className="field-sizing-content max-h-120 min-h-80 font-mono text-xs md:text-xs"
          disabled={disabled}
          id={id}
          onChange={(event) => {
            onChange(event.currentTarget.value)
          }}
          value={value}
        />
      </TabsContent>
    </Tabs>
  )
}
