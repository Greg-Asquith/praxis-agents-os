// apps/web/src/lib/react-node.ts

import { isValidElement, type ReactNode } from "react"

export function reactNodeToText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") {
    return ""
  }
  if (typeof node === "string" || typeof node === "number") {
    return String(node)
  }
  if (isReactNodeArray(node)) {
    return node.map(reactNodeToText).join("")
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return reactNodeToText(node.props.children)
  }
  return ""
}

export function isReactNodeArray(node: ReactNode): node is ReactNode[] {
  return Array.isArray(node)
}
