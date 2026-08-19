import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * JSX text is not a string literal.
 *
 * An escape sequence written bare between tags renders as its own characters -
 * backslash, u, 0, 6 and so on - because JSX children are text, not source
 * code. The same sequence inside braces is a string literal and unescapes to
 * Persian.
 *
 * A customer saw the difference: the retry button on the Mini App's error
 * screen showed twelve literal escape characters while the Persian message
 * directly above it, written in braces, read correctly.
 *
 * Nothing else catches this. It compiles, it type-checks, it builds, and the
 * only symptom is Persian copy replaced on screen by its own source spelling.
 */

// From the project root: vitest runs with cwd set to it, and import.meta.url
// is not a file: URL under this runner.
const SOURCE = join(process.cwd(), 'src')

function tsxFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry)
    if (statSync(path).isDirectory()) return tsxFiles(path)
    return path.endsWith('.tsx') ? [path] : []
  })
}

/**
 * Everything inside quotes, gone.
 *
 * A legitimate escape always lives in a string literal, so whatever survives
 * this removal is sitting in JSX text. Matching the line as a whole cannot
 * tell the two apart: the first version of this test looked for an escape
 * after a `>` on the same line, and missed the actual bug - which sat on its
 * own line, below the tag.
 */
function outsideStrings(line: string): string {
  return line
    .replace(/'[^']*'/g, "''")
    .replace(/"[^"]*"/g, '""')
    .replace(/`[^`]*`/g, '``')
}

const ESCAPE = /\\u[0-9a-fA-F]{4}/

describe('persian copy in JSX', () => {
  it('is never written as a bare escape sequence between tags', () => {
    const offenders = tsxFiles(SOURCE).flatMap((path) =>
      readFileSync(path, 'utf8')
        .split('\n')
        .map((line, index) => ({ line, number: index + 1 }))
        // Comments explain this very bug and are allowed to spell it out.
        .filter(({ line }) => !line.trim().startsWith('//') && !line.trim().startsWith('*'))
        .filter(({ line }) => ESCAPE.test(outsideStrings(line)))
        .map(({ number, line }) => `${path}:${number}: ${line.trim()}`),
    )

    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
