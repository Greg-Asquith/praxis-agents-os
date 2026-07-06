// apps/web/src/features/files/diff.ts

export type LineDiffItem = {
  kind: "same" | "added" | "removed"
  text: string
}

const MAX_DIFF_LINES = 1_000
const MAX_DIFF_CHARS = 100_000

export function diffTooLarge(left: string, right: string) {
  return (
    left.length + right.length > MAX_DIFF_CHARS ||
    lineCount(left) + lineCount(right) > MAX_DIFF_LINES
  )
}

export function lineDiff(left: string, right: string): LineDiffItem[] {
  const leftLines = splitLines(left)
  const rightLines = splitLines(right)
  const table = buildLcsTable(leftLines, rightLines)
  const output: LineDiffItem[] = []
  let leftIndex = 0
  let rightIndex = 0

  while (leftIndex < leftLines.length && rightIndex < rightLines.length) {
    if (leftLines[leftIndex] === rightLines[rightIndex]) {
      output.push({ kind: "same", text: leftLines[leftIndex] ?? "" })
      leftIndex += 1
      rightIndex += 1
    } else if (cell(table, leftIndex + 1, rightIndex) >= cell(table, leftIndex, rightIndex + 1)) {
      output.push({ kind: "removed", text: leftLines[leftIndex] ?? "" })
      leftIndex += 1
    } else {
      output.push({ kind: "added", text: rightLines[rightIndex] ?? "" })
      rightIndex += 1
    }
  }

  while (leftIndex < leftLines.length) {
    output.push({ kind: "removed", text: leftLines[leftIndex] ?? "" })
    leftIndex += 1
  }
  while (rightIndex < rightLines.length) {
    output.push({ kind: "added", text: rightLines[rightIndex] ?? "" })
    rightIndex += 1
  }

  return output
}

function buildLcsTable(leftLines: string[], rightLines: string[]) {
  const table = Array.from({ length: leftLines.length + 1 }, () =>
    Array.from({ length: rightLines.length + 1 }, () => 0)
  )

  for (let leftIndex = leftLines.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = rightLines.length - 1; rightIndex >= 0; rightIndex -= 1) {
      const row = table[leftIndex]
      if (!row) {
        continue
      }
      row[rightIndex] =
        leftLines[leftIndex] === rightLines[rightIndex]
          ? cell(table, leftIndex + 1, rightIndex + 1) + 1
          : Math.max(cell(table, leftIndex + 1, rightIndex), cell(table, leftIndex, rightIndex + 1))
    }
  }

  return table
}

function cell(table: number[][], row: number, column: number) {
  return table[row]?.[column] ?? 0
}

function splitLines(value: string) {
  return value.split(/\r?\n/)
}

function lineCount(value: string) {
  if (!value) {
    return 0
  }
  return splitLines(value).length
}
