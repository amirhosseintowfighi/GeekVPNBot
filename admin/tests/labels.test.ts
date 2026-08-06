import { describe, expect, it } from 'vitest'

import {
  BROADCAST_STATE,
  LOG_LEVEL,
  PAYMENT_METHOD,
  PAYMENT_STATE,
  PLAN_TYPE,
  PUBLICATION_STATE,
  SERVER_HEALTH,
  SUBSCRIPTION_STATE,
  TICKET_STATE,
  TRANSACTION_KIND,
  USER_STATE,
  waitTone,
} from '@/lib/labels'

const ALL_MAPS = {
  PAYMENT_STATE,
  PAYMENT_METHOD,
  SUBSCRIPTION_STATE,
  PLAN_TYPE,
  PUBLICATION_STATE,
  USER_STATE,
  SERVER_HEALTH,
  TICKET_STATE,
  TRANSACTION_KIND,
  BROADCAST_STATE,
  LOG_LEVEL,
}

describe('label maps', () => {
  it('never leaks an English enum value into the interface', () => {
    // Every state the backend can emit must have a Persian rendering. A
    // missing entry would surface as raw snake_case in front of a customer
    // support agent mid-incident.
    for (const [mapName, map] of Object.entries(ALL_MAPS)) {
      for (const [key, meta] of Object.entries(map)) {
        expect(meta.fa, mapName + '.' + key).toBeTruthy()
        expect(/[a-zA-Z_]/.test(meta.fa), mapName + '.' + key + ' = ' + meta.fa).toBe(false)
      }
    }
  })

  it('assigns a tone to every state, since bare grey text defeats the point', () => {
    for (const map of Object.values(ALL_MAPS)) {
      for (const meta of Object.values(map)) {
        expect(meta.tone).toBeTruthy()
      }
    }
  })

  it('colours settled money green and failed money red', () => {
    expect(PAYMENT_STATE.approved.tone).toBe('success')
    expect(PAYMENT_STATE.pending_review.tone).toBe('warning')
    expect(PAYMENT_STATE.rejected.tone).toBe('destructive')
  })

  it('does not colour an expired subscription as an error', () => {
    // Expiry is the normal end of a lifecycle, not a fault. Painting it red
    // trains operators to ignore red.
    expect(SUBSCRIPTION_STATE.expired.tone).not.toBe('destructive')
    expect(SERVER_HEALTH.down.tone).toBe('destructive')
  })
})

describe('waitTone', () => {
  it('stays quiet inside the thirty-minute promise made in the FAQ', () => {
    expect(waitTone(0)).toBe('muted')
    expect(waitTone(29)).toBe('muted')
  })

  it('turns amber exactly at thirty minutes', () => {
    // Boundary is inclusive: at minute thirty the promise is spent, not
    // nearly spent.
    expect(waitTone(30)).toBe('warning')
    expect(waitTone(119)).toBe('warning')
  })

  it('turns red at two hours', () => {
    expect(waitTone(120)).toBe('destructive')
    expect(waitTone(5000)).toBe('destructive')
  })

  it('treats nonsense input as calm rather than alarming', () => {
    expect(waitTone(-5)).toBe('muted')
  })
})
