import { describe, expect, it } from 'vitest'

import { permissionsFor } from '@/lib/rbac'
import type { Permission, Role } from '@/lib/rbac'
import { landingFor } from '@/lib/nav'

const canFor = (role: Role) => {
  const held = new Set<string>(permissionsFor(role))
  return (permission: Permission) => held.has(permission)
}

describe('where a person lands after signing in', () => {
  it('sends a reseller to their own panel', () => {
    // They signed in successfully and were shown "دسترسی ندارید": sign-in
    // drops everybody on `/`, which is gated on a permission a reseller
    // deliberately does not hold.
    expect(landingFor(canFor('reseller'))).toBe('/portal')
  })

  it('leaves staff on the dashboard', () => {
    expect(landingFor(canFor('super_admin'))).toBe('/')
    expect(landingFor(canFor('support'))).not.toBe('/portal')
  })

  it('has an answer for somebody who can see nothing', () => {
    expect(landingFor(() => false)).toBe('/')
  })
})
