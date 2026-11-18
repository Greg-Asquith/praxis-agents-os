// apps/web/src/features/email-suppressions/parse-addresses.ts

const WRAPPER = /^[\s<("'[]+|[\s>)"'\],.]+$/g

// Reads anything containing an @ so names around "Name <address>" drop out; the server validates.
export function parsePastedAddresses(text: string): string[] {
  const addresses = new Set<string>()
  for (const token of text.split(/[\s,;]+/)) {
    const value = token
      .replace(WRAPPER, "")
      .replace(/^mailto:/i, "")
      .toLowerCase()
    if (value.includes("@")) addresses.add(value)
  }
  return [...addresses]
}
