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
 *
 * They used to be written in a vocabulary of this file's own invention -
 * `owner`, `users.view`, `permissions.edit` - none of which the API has ever
 * issued. Every assertion passed and none of them described the product: the
 * matrix they were guarding was unreachable from a real session. The names
 * here are now the API's, and `test_admin_rbac_contract.py` fails if they
 * drift from it again.
 */
describe('role matrix', () => {
  it('gives the super admin every permission, including the ones nobody else has', () => {
    const owner = permissionsFor('super_admin')

    for (const role of ROLES) {
      for (const permission of permissionsFor(role)) {
        expect(owner).toContain(permission)
      }
    }

    expect(owner).toContain('admins.write')
    expect(owner).toContain('users.impersonate')
  })

  it('reserves administrator creation and impersonation for the super admin alone', () => {
    for (const role of ROLES.filter((candidate) => candidate !== 'super_admin')) {
      expect(permissionsFor(role)).not.toContain('admins.write')
      expect(permissionsFor(role)).not.toContain('users.impersonate')
    }
  })

  it('keeps finance out of customer conversations', () => {
    // Finance can see an order to reconcile a refund against it, but must not
    // answer the customer: support owns the voice of the brand.
    const finance = permissionsFor('finance')
    expect(finance).toContain('orders.read')
    expect(finance).not.toContain('tickets.reply')
  })

  it('keeps support away from money movement', () => {
    const support = permissionsFor('support')
    expect(support).toContain('orders.read')
    expect(support).not.toContain('orders.refund')
    expect(support).not.toContain('wallet.adjust')
  })

  it('makes the viewer strictly read-only', () => {
    const writes = permissionsFor('viewer').filter(
      (permission) => !permission.endsWith('.read') && permission !== 'analytics.view',
    )
    expect(writes).toEqual([])
  })

  it('never grants a write permission without its matching read permission', () => {
    for (const role of ROLES) {
      const held = permissionsFor(role)
      for (const permission of held) {
        const [resource = '', action] = permission.split('.')
        if (action === 'read') continue
        // Permissions whose resource has no `.read` of its own: the screen
        // that exercises them is gated by a different resource.
        if (['analytics', 'campaigns', 'broadcast', 'metrics', 'audit'].includes(resource)) continue
        // A screen you cannot open is a permission you cannot exercise.
        expect(held).toContain(resource + '.read')
      }
    }
  })
})

describe('can', () => {
  it('reads the list the server issued, not a role', () => {
    expect(can(['tickets.read'], 'tickets.read')).toBe(true)
    expect(can(['tickets.read'], 'tickets.reply')).toBe(false)
  })

  it('denies while the session is still loading', () => {
    // Null is "we do not know yet". Rendering a destructive button on a guess
    // and withdrawing it a moment later is worse than showing it a beat late.
    expect(can(null, 'orders.refund')).toBe(false)
    expect(can(undefined, 'orders.refund')).toBe(false)
  })

  it('denies a permission the server has never heard of', () => {
    // The failure that started this: an unknown name must lock a door. It does
    // - which is why the vocabulary has to match, because a typo and a
    // deliberate denial are indistinguishable from here.
    expect(can(['users.view' as never], 'users.read')).toBe(false)
  })
})

describe('canAny / canAll', () => {
  it('treats an empty requirement list as satisfied for canAll and unsatisfied for canAny', () => {
    expect(canAll(['users.read'], [])).toBe(true)
    expect(canAny(['users.read'], [])).toBe(false)
  })

  it('short-circuits correctly on mixed lists', () => {
    const support = permissionsFor('support')
    expect(canAny(support, ['orders.refund', 'tickets.reply'])).toBe(true)
    expect(canAll(support, ['orders.refund', 'tickets.reply'])).toBe(false)
  })
})

describe('canAssignRole', () => {
  const owner = permissionsFor('super_admin')

  it('never allows the super admin role to be handed out, not even by a super admin', () => {
    // Ownership transfer is an out-of-band operation on purpose. If it were a
    // dropdown, a compromised owner session would be a permanent takeover.
    for (const role of ROLES) {
      expect(canAssignRole(role, 'super_admin', permissionsFor(role))).toBe(false)
    }
  })

  it('forbids assigning a role at or above your own rank', () => {
    expect(canAssignRole('admin', 'admin', owner)).toBe(false)
    expect(canAssignRole('finance', 'admin', owner)).toBe(false)
    // Finance and support share a rank, so neither can reassign the other.
    expect(ROLE_RANK.finance).toBe(ROLE_RANK.support)
    expect(canAssignRole('finance', 'support', owner)).toBe(false)
  })

  it('lets the super admin assign every role below their own', () => {
    expect(canAssignRole('super_admin', 'admin', owner)).toBe(true)
    expect(canAssignRole('super_admin', 'finance', owner)).toBe(true)
    expect(canAssignRole('super_admin', 'viewer', owner)).toBe(true)
  })

  it('needs admins.write as well as the rank, which only the super admin holds', () => {
    // Outranking someone is not authority over their role. admin outranks
    // finance and still may not assign it: `admins.write` is the gate, and the
    // super admin is the only role holding it.
    expect(ROLE_RANK.admin).toBeGreaterThan(ROLE_RANK.finance)
    expect(permissionsFor('admin')).not.toContain('admins.write')
    expect(canAssignRole('admin', 'finance', permissionsFor('admin'))).toBe(false)
    expect(canAssignRole('finance', 'viewer', permissionsFor('finance'))).toBe(false)
  })

  it('gives the viewer no assignment powers at all', () => {
    for (const role of ROLES) {
      expect(canAssignRole('viewer', role, permissionsFor('viewer'))).toBe(false)
    }
  })

  it('closes the self-promotion loop', () => {
    // The whole point of the rank rule: no chain of legal assignments lets a
    // non-super-admin reach admin or above.
    expect(canAssignRole('admin', 'super_admin', owner)).toBe(false)
    expect(canAssignRole('admin', 'admin', owner)).toBe(false)
  })
})
