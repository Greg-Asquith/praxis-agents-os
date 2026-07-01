// apps/web/src/lib/react-node.ts

import { isValidElement, type ReactNode } from "react"

export function reactNodeToText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") {
    return ""
  }
  if (typeof node === "string" || typeof node === "number") {
    return String(node)
  }
  if (Array.isArray(node)) {
    return (node as ReactNode[]).map(reactNodeToText).join("")
  }
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode }
    return reactNodeToText(props.children)
  }
  return ""
}
