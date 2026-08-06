import { describe, expect, it } from 'vitest'

import { can } from '@/lib/rbac'
import type { PaymentState, Role } from '@/lib/types'

/**
 * Order action gating.
 *
 * The order detail screen decides which buttons exist from two independent
 * inputs: the payment state and the operator's role. Getting either wrong is
 * a money bug, so the decision is expressed here as a pure function and
 * pinned, rather than left implicit in JSX.
 *
 * The rule the screen follows: an action is RENDERED only when the state
 * permits it, and ENABLED only when the role permits it. Illegal-by-state
 * actions are hidden rather than disabled, because a greyed-out "refund"
 * button on an unpaid order invites a support ticket asking why it is grey.
 */
type Action = 'approve' | 'reject' | 'refund'

const STATE_ALLOWS: Record<PaymentState, Action[]> = {
  awaiting_receipt: [],
  pending_review: ['approve', 'reject'],
  approved: ['refund'],
  rejected: [],
  refunded: [],
  expired: [],
}

const PERMISSION_FOR: Record<Action, 'orders.approve' | 'orders.reject' | 'orders.refund'> = {
  approve: 'orders.approve',
  reject: 'orders.reject',
  refund: 'orders.refund',
}

const visibleActions = (state: PaymentState): Action[] => STATE_ALLOWS[state]
const allowedActions = (state: PaymentState, role: Role): Action[] =>
  visibleActions(state).filter((action) => can(role, PERMISSION_FOR[action]))

describe('state gating', () => {
  it('offers approve and reject only while a payment is under review', () => {
    expect(visibleActions('pending_review').sort()).toEqual(['approve', 'reject'])
  })

  it('offers nothing on an order whose receipt has not arrived yet', () => {
    // There is nothing to approve: the customer has not paid.
    expect(visibleActions('awaiting_receipt')).toEqual([])
  })

  it('offers refund only after money has actually been taken', () => {
    expect(visibleActions('approved')).toEqual(['refund'])
  })

  it('makes every terminal state inert', () => {
    for (const state of ['rejected', 'refunded', 'expired'] as PaymentState[]) {
      expect(visibleActions(state)).toEqual([])
    }
  })

  it('never allows approving and refunding the same order at the same moment', () => {
    for (const actions of Object.values(STATE_ALLOWS)) {
      expect(actions.includes('approve') && actions.includes('refund')).toBe(false)
    }
  })

  it('can never refund an order twice', () => {
    expect(visibleActions('refunded')).not.toContain('refund')
  })
})

describe('role gating on top of state gating', () => {
  it('lets finance clear the review queue', () => {
    expect(allowedActions('pending_review', 'finance').sort()).toEqual(['approve', 'reject'])
    expect(allowedActions('approved', 'finance')).toEqual(['refund'])
  })

  it('lets support triage but not move money back out', () => {
    // Support may reject an obviously bogus receipt, but a refund touches a
    // settled balance and stays with finance.
    expect(allowedActions('approved', 'support')).toEqual([])
  })

  it('gives the viewer no order actions in any state', () => {
    for (const state of Object.keys(STATE_ALLOWS) as PaymentState[]) {
      expect(allowedActions(state, 'viewer')).toEqual([])
    }
  })

  it('never lets a role act where the state forbids it, however privileged', () => {
    // Permission can only ever subtract from what the state allows.
    for (const state of Object.keys(STATE_ALLOWS) as PaymentState[]) {
      expect(allowedActions(state, 'owner').length).toBeLessThanOrEqual(
        visibleActions(state).length,
      )
    }
    expect(allowedActions('refunded', 'owner')).toEqual([])
  })
})

describe('reason requirement', () => {
  const MIN_REASON = 5
  const reasonValid = (action: Action, reason: string) =>
    action === 'approve' ? true : reason.trim().length >= MIN_REASON

  it('demands a written reason for anything that disappoints a customer', () => {
    expect(reasonValid('reject', '')).toBe(false)
    expect(reasonValid('reject', '\u0628\u062f')).toBe(false)
    expect(reasonValid('refund', '   ')).toBe(false)
  })

  it('does not obstruct the happy path', () => {
    expect(reasonValid('approve', '')).toBe(true)
  })

  it('accepts a real Persian explanation', () => {
    expect(reasonValid('reject', '\u0631\u0633\u06cc\u062f \u0646\u0627\u0645\u0639\u062a\u0628\u0631 \u0627\u0633\u062a')).toBe(true)
  })
})
