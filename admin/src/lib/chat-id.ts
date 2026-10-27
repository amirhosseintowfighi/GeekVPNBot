import { normalizeInput } from '@/lib/fa'

/**
 * Editing a Telegram chat id: a group or channel id is negative.
 *
 * Kept as a string while typed, because a controlled number box cannot hold a
 * lone "-" - it collapses to 0 and the operator can never get past it. Turned
 * into a number only when saved.
 */
export function editChatId(raw: string): string {
  const text = normalizeInput(raw).replace(/[−–‐]/g, '-')
  const negative = text.startsWith('-')
  const digits = text.replace(/[^\d]/g, '')
  return (negative ? '-' : '') + digits
}

/** The number to store. Empty or a lone "-" means 0, which switches it off. */
export function chatIdToSave(value: string | number): number {
  if (typeof value === 'number') return value
  const cleaned = editChatId(value)
  if (cleaned === '' || cleaned === '-') return 0
  return Number(cleaned)
}
