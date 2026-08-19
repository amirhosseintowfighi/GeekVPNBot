/**
 * Role-based access control for the admin panel.
 *
 * Two rules govern everything in this file:
 *
 * 1. **This is a UI concern only.** Hiding a button is a courtesy to the
 *    operator, not a security boundary. Every permission here MUST be checked
 *    again server-side. Anyone can open devtools and flip a boolean; nobody
 *    can forge a server-side role check.
 *
 * 2. **Deny by default.** An unknown permission or an unknown role resolves to
 *    false. A missing entry in the matrix must lock a door, never open one.
 */

export const ROLES = [
  'owner',
  'admin',
  'finance',
  'support',
  'viewer',
] as const

export type Role = (typeof ROLES)[number]

/**
 * Permissions are `resource.action`. Read and write are always separate:
 * a support agent must be able to see an order to answer a question about it
 * without being able to refund it.
 */
export const PERMISSIONS = [
  'dashboard.view',

  'users.view',
  'users.edit',
  'users.suspend',
  'users.impersonate',

  'orders.view',
  'orders.approve',
  'orders.reject',
  'orders.refund',

  'products.view',
  'products.edit',
  'products.publish',

  'panels.view',
  'panels.edit',
  'panels.test',

  'servers.view',
  'servers.edit',

  'coupons.view',
  'coupons.edit',

  'campaigns.view',
  'campaigns.edit',

  'analytics.view',
  'analytics.export',

  'broadcast.view',
  'broadcast.send',

  'tickets.view',
  'tickets.reply',
  'tickets.close',

  'wallet.view',
  'wallet.adjust',

  'logs.view',

  'settings.view',
  'settings.edit',

  'permissions.view',
  'permissions.edit',
] as const

export type Permission = (typeof PERMISSIONS)[number]

export const ROLE_LABEL_FA: Record<Role, string> = {
  owner: '\u0645\u0627\u0644\u06a9',
  admin: '\u0645\u062f\u06cc\u0631',
  finance: '\u0645\u0627\u0644\u06cc',
  support: '\u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc',
  viewer: '\u0646\u0627\u0638\u0631',
}

export const ROLE_DESCRIPTION_FA: Record<Role, string> = {
  owner:
    '\u062f\u0633\u062a\u0631\u0633\u06cc \u06a9\u0627\u0645\u0644\u060c \u0634\u0627\u0645\u0644 \u062a\u063a\u06cc\u06cc\u0631 \u062f\u0633\u062a\u0631\u0633\u06cc \u062f\u06cc\u06af\u0631\u0627\u0646',
  admin:
    '\u0647\u0645\u0647\u200c\u0686\u06cc\u0632 \u0628\u0647\u200c\u062c\u0632 \u062a\u063a\u06cc\u06cc\u0631 \u0646\u0642\u0634\u200c\u0647\u0627 \u0648 \u062a\u0646\u0638\u06cc\u0645\u0627\u062a \u062d\u0633\u0627\u0633',
  finance:
    '\u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627\u060c \u067e\u0631\u062f\u0627\u062e\u062a\u200c\u0647\u0627\u060c \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0648 \u06af\u0632\u0627\u0631\u0634\u200c\u0647\u0627',
  support:
    '\u062a\u06cc\u06a9\u062a\u200c\u0647\u0627 \u0648 \u0645\u0634\u0627\u0647\u062f\u0647\u200c\u06cc \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u06a9\u0627\u0631\u0628\u0631',
  viewer:
    '\u0641\u0642\u0637 \u062e\u0648\u0627\u0646\u062f\u0646\u060c \u0628\u062f\u0648\u0646 \u0647\u06cc\u0686 \u062a\u063a\u06cc\u06cc\u0631\u06cc',
}

/**
 * The matrix.
 *
 * `owner` is deliberately NOT written out. It is granted everything by the
 * check below, so adding a new permission to the list above cannot silently
 * lock the owner out of a feature they are supposed to administer.
 *
 * Notable deliberate omissions:
 * - Nobody but `owner` gets `permissions.edit`. Privilege escalation is the
 *   one thing an operator must never be able to do for themselves.
 * - `users.impersonate` is owner-only. Acting as a customer is the single
 *   most abusable capability in the product.
 * - `finance` cannot reply to tickets, and `support` cannot refund. Keeping
 *   the person who talks to the customer separate from the person who moves
 *   the money is the cheapest fraud control there is.
 */
const MATRIX: Record<Exclude<Role, 'owner'>, Permission[]> = {
  admin: [
    'dashboard.view',
    'users.view',
    'users.edit',
    'users.suspend',
    'orders.view',
    'orders.approve',
    'orders.reject',
    'orders.refund',
    'products.view',
    'products.edit',
    'products.publish',
    'panels.view',
    'panels.edit',
    'panels.test',
    'servers.view',
    'servers.edit',
    'coupons.view',
    'coupons.edit',
    'campaigns.view',
    'campaigns.edit',
    'analytics.view',
    'analytics.export',
    'broadcast.view',
    'broadcast.send',
    'tickets.view',
    'tickets.reply',
    'tickets.close',
    'wallet.view',
    'wallet.adjust',
    'logs.view',
    'settings.view',
    'settings.edit',
    'permissions.view',
  ],

  finance: [
    'dashboard.view',
    'users.view',
    'orders.view',
    'orders.approve',
    'orders.reject',
    'orders.refund',
    'products.view',
    'coupons.view',
    'campaigns.view',
    'analytics.view',
    'analytics.export',
    'wallet.view',
    'wallet.adjust',
    // Read-only on tickets: finance reconciles a refund against the
    // conversation that caused it, but support owns the voice of the brand.
    'tickets.view',
    'logs.view',
  ],

  support: [
    'dashboard.view',
    'users.view',
    'orders.view',
    'products.view',
    'servers.view',
    'tickets.view',
    'tickets.reply',
    'tickets.close',
    'wallet.view',
  ],

  viewer: [
    'dashboard.view',
    'users.view',
    'orders.view',
    'products.view',
    'panels.view',
    'servers.view',
    'coupons.view',
    'campaigns.view',
    'analytics.view',
    'tickets.view',
    'wallet.view',
    'logs.view',
    'settings.view',
  ],
}

const SETS: Record<Role, ReadonlySet<Permission>> = {
  owner: new Set(PERMISSIONS),
  admin: new Set(MATRIX.admin),
  finance: new Set(MATRIX.finance),
  support: new Set(MATRIX.support),
  viewer: new Set(MATRIX.viewer),
}

/** Deny by default: an unknown role has no permissions at all. */
export function can(role: Role | null | undefined, permission: Permission): boolean {
  if (!role) return false
  const set = SETS[role]
  if (!set) return false
  return set.has(permission)
}

/** True when the role holds at least one of the permissions. */
export function canAny(
  role: Role | null | undefined,
  permissions: readonly Permission[],
): boolean {
  return permissions.some((permission) => can(role, permission))
}

/** True only when the role holds every permission. */
export function canAll(
  role: Role | null | undefined,
  permissions: readonly Permission[],
): boolean {
  return permissions.every((permission) => can(role, permission))
}

export function permissionsFor(role: Role): Permission[] {
  return PERMISSIONS.filter((permission) => can(role, permission))
}

/**
 * Roles ordered from most to least privileged, used to render the permission
 * matrix and to stop an operator from assigning a role above their own.
 */
export const ROLE_RANK: Record<Role, number> = {
  owner: 4,
  admin: 3,
  finance: 2,
  support: 2,
  viewer: 1,
}

/**
 * `finance` and `support` deliberately share a rank: neither may promote the
 * other, and neither may promote itself. Only a strictly higher rank assigns,
 * which is what `canAssignRole` enforces.
 */

/**
 * An operator may only assign a role strictly below their own rank.
 *
 * Without this, an admin can promote a colleague to admin, and the role
 * boundary stops meaning anything after the first friendly favour.
 */
export function canAssignRole(actor: Role, target: Role): boolean {
  if (actor === 'owner') return target !== 'owner'
  if (!can(actor, 'permissions.edit')) return false
  return ROLE_RANK[actor] > ROLE_RANK[target]
}
