import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { ORDER_STATE, orderStateMeta } from '@/lib/labels'

/**
 * Reported: the orders page errored under some filters.
 *
 * The backend has a `cancelled` order state the panel had no label for. The
 * row read `ORDER_STATE[order.state].tone`, which is a TypeError on
 * `undefined`, so any page holding one cancelled order - "every state" among
 * them - took the whole screen down. The list here is read from the backend
 * enum, so the next state added there fails this test instead of the page.
 */
describe('order states', () => {
  const source = readFileSync(
    resolve(__dirname, '../../src/geekvpn/domain/provisioning/enums.py'),
    'utf8',
  )
  const block = source.slice(source.indexOf('class OrderState'), source.indexOf('@property'))
  const backend = [...block.matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1])

  it('has a Persian label for every state the backend can send', () => {
    expect(backend.length).toBeGreaterThan(5)
    for (const state of backend) {
      expect(ORDER_STATE[state as keyof typeof ORDER_STATE]?.fa, state).toBeTruthy()
    }
  })

  it('still renders a state it does not know, rather than crashing the page', () => {
    expect(orderStateMeta('something_new').fa).toBe('something_new')
  })
})
