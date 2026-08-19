import { describe, expect, it } from 'vitest'

import {
  ROLES,
  ROLE_RANK,
  can,
  canAll,
  canAny,
  canAssignRole,
  permissionsFor,
} from '@/lib/rbac'

/**
 * RBAC.
 *
 * These tests assert the *denials*, not the grants. A role matrix that lets
 * everyone do everything passes any test written around "can the owner do X".
 * The valuable assertions are the ones that fail loudly the day somebody adds
 * a permission to the wrong row.
 */
describe('role matrix', () => {
  it('gives the owner every permission, including the ones nobody else has', () => {
    for (const role of ROLES) {
      for (const permission of permissionsFor(role)) {
        expect(can('owner', permission)).toBe(true)
      }
    }

    expect(can('owner', 'permissions.edit')).toBe(true)
    expect(can('owner', 'users.impersonate')).toBe(true)
  })

  it('reserves permission editing and impersonation for the owner alone', () => {
    for (const role of ROLES.filter((candidate) => candidate !== 'owner')) {
      expect(can(role, 'permissions.edit')).toBe(false)
      expect(can(role, 'users.impersonate')).toBe(false)
    }
  })

  it('keeps finance out of customer conversations', () => {
    // Finance can see a ticket to reconcile a refund against it, but must not
    // answer the customer: support owns the voice of the brand.
    expect(can('finance', 'tickets.view')).toBe(true)
    expect(can('finance', 'tickets.reply')).toBe(false)
    expect(can('finance', 'tickets.close')).toBe(false)
  })

  it('keeps support away from money movement', () => {
    expect(can('support', 'orders.view')).toBe(true)
    expect(can('support', 'orders.refund')).toBe(false)
    expect(can('support', 'wallet.adjust')).toBe(false)
  })

  it('makes the viewer strictly read-only', () => {
    const writes = permissionsFor('viewer').filter(
      (permission) => !permission.endsWith('.view'),
    )
    expect(writes).toEqual([])
  })

  it('never grants an edit permission without its matching view permission', () => {
    for (const role of ROLES) {
      for (const permission of permissionsFor(role)) {
        const [resource, action] = permission.split('.')
        if (action === 'view') continue
        // A screen you cannot open is a permission you cannot exercise.
        expect(can(role, (resource + '.view') as never)).toBe(true)
      }
    }
  })
})

describe('canAny / canAll', () => {
  it('treats an empty requirement list as satisfied for canAll and unsatisfied for canAny', () => {
    expect(canAll('viewer', [])).toBe(true)
    expect(canAny('viewer', [])).toBe(false)
  })

  it('short-circuits correctly on mixed lists', () => {
    expect(canAny('support', ['orders.refund', 'tickets.reply'])).toBe(true)
    expect(canAll('support', ['orders.refund', 'tickets.reply'])).toBe(false)
  })
})

describe('canAssignRole', () => {
  it('never allows the owner role to be handed out, not even by an owner', () => {
    // Ownership transfer is an out-of-band operation on purpose. If it were a
    // dropdown, a compromised owner session would be a permanent takeover.
    for (const role of ROLES) {
      expect(canAssignRole(role, 'owner')).toBe(false)
    }
  })

  it('forbids assigning a role at or above your own rank', () => {
    expect(canAssignRole('admin', 'admin')).toBe(false)
    expect(canAssignRole('finance', 'admin')).toBe(false)
    // Finance and support share a rank, so neither can reassign the other.
    expect(ROLE_RANK.finance).toBe(ROLE_RANK.support)
    expect(canAssignRole('finance', 'support')).toBe(false)
  })

  it('lets the owner assign every role below their own', () => {
    expect(canAssignRole('owner', 'admin')).toBe(true)
    expect(canAssignRole('owner', 'finance')).toBe(true)
    expect(canAssignRole('owner', 'viewer')).toBe(true)
  })

  it('needs permissions.edit as well as the rank, which only the owner has', () => {
    // Outranking someone is not authority over their role. admin outranks
    // finance and still may not assign it: `permissions.edit` is the gate, and
    // the owner is the only role holding it - which is exactly what the owner's
    // own description promises ("full access, including changing others'").
    //
    // This test used to assert that admin and finance could both assign
    // downwards. It had never been run, and asserting it would have meant
    // widening who can hand out authority.
    expect(ROLE_RANK.admin).toBeGreaterThan(ROLE_RANK.finance)
    expect(can('admin', 'permissions.edit')).toBe(false)
    expect(canAssignRole('admin', 'finance')).toBe(false)
    expect(canAssignRole('finance', 'viewer')).toBe(false)
  })

  it('gives the viewer no assignment powers at all', () => {
    for (const role of ROLES) {
      expect(canAssignRole('viewer', role)).toBe(false)
    }
  })

  it('closes the self-promotion loop', () => {
    // The whole point of the rank rule: no chain of legal assignments lets a
    // non-owner reach admin or above.
    expect(canAssignRole('admin', 'owner')).toBe(false)
    expect(canAssignRole('admin', 'admin')).toBe(false)
  })
})
