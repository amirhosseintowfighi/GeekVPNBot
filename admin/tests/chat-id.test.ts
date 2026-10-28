import { describe, expect, it } from 'vitest'

import { chatIdToSave, editChatId } from '@/lib/chat-id'

/**
 * Telegram group and channel ids are negative.
 *
 * The settings screen's number box stripped everything but digits, the minus
 * sign included, so `-1004423033275` could never be entered: typing "-" reset
 * the field to 0, and a backup channel set to 0 sends the backup to whoever
 * pressed the button instead. Seven settings were affected - the backup channel
 * and every notification group.
 */
describe('editChatId', () => {
  it('lets the operator start with a minus sign', () => {
    expect(editChatId('-')).toBe('-')
  })

  it('keeps a channel id as typed', () => {
    expect(editChatId('-1004423033275')).toBe('-1004423033275')
  })

  it('accepts Persian digits and stray spaces from a paste', () => {
    expect(editChatId(' -۱۰۰۴۴۲۳۰۳۳۲۷۵ ')).toBe('-1004423033275')
  })

  it('takes the typographic minus a phone keyboard may insert', () => {
    expect(editChatId('−1004423033275')).toBe('-1004423033275')
  })

  it('allows a minus only at the start', () => {
    expect(editChatId('-100-44')).toBe('-10044')
  })

  it('drops anything that is not part of a number', () => {
    expect(editChatId('-100abc44')).toBe('-10044')
  })
})

describe('chatIdToSave', () => {
  it('saves a negative channel id as a negative number', () => {
    expect(chatIdToSave('-1004423033275')).toBe(-1004423033275)
  })

  it('saves a private chat id as typed', () => {
    expect(chatIdToSave('87791922')).toBe(87791922)
  })

  it('treats an empty or half-typed field as off', () => {
    expect(chatIdToSave('')).toBe(0)
    expect(chatIdToSave('-')).toBe(0)
  })

  it('passes a value already stored as a number through', () => {
    expect(chatIdToSave(-1004423033275)).toBe(-1004423033275)
  })
})
