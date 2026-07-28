// apps/web/src/lib/csv.ts

export function parseCsv(content: string, maxRows = Infinity): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let value = ""
  let quoted = false

  for (let index = 0; index < content.length; index += 1) {
    const character = content[index] ?? ""
    if (character === '"') {
      if (quoted && content[index + 1] === '"') {
        value += '"'
        index += 1
      } else {
        quoted = !quoted
      }
      continue
    }
    if (character === "," && !quoted) {
      row.push(value)
      value = ""
      continue
    }
    if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && content[index + 1] === "\n") {
        index += 1
      }
      row.push(value)
      if (row.some((cell) => cell.length > 0)) {
        rows.push(row)
        if (rows.length >= maxRows) {
          return rows
        }
      }
      row = []
      value = ""
      continue
    }
    value += character
  }

  row.push(value)
  if (row.some((cell) => cell.length > 0) && rows.length < maxRows) {
    rows.push(row)
  }
  return rows
}
