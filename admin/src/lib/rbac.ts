/**
 * Role-based access control for the admin panel.
 *
 * Three rules govern everything in this file:
 *
 * 1. **This is a UI concern only.** Hiding a button is a courtesy to the
 *    operator, not a security boundary. Every permission here MUST be checked
 *    again server-side. Anyone can open devtools and flip a boolean; nobody
 *    can forge a server-side role check.
 *
 * 2. **The server decides, this file only reads.** `can()` asks the permission
 *    list the API issued for the signed-in operator. It used to derive the
 *    answer from a role matrix kept here, in a vocabulary the backend had
 *    never heard of - roles named `owner` where the API says `super_admin`,
 *    permissions named `users.view` where the API says `users.read`. Every
 *    name missed, and since rule 3 denies by default, a super admin who signed
 *    in successfully was refused every screen in the product.
 *
 * 3. **Deny by default.** An unknown permission resolves to false. A missing
 *    entry must lock a door, never open one - which is why rule 2 matters so
 *    much: under deny-by-default, a vocabulary mismatch is indistinguishable
 *    from a deliberate denial, and it locks out the owner rather than letting
 *    a stranger in.
 *
 * The names below are the API's own, copied from
 * `domain/identity/permissions.py`. `tests/integration/test_admin_rbac_contract.py`
 * fails if the two drift apart again.
 */

export const ROLES = [
  'super_admin',
  'admin',
  'finance',
  'support',
  'viewer',
  // Not a member of staff. A reseller signs in through the same door with
  // a role that resolves to almost nothing, and every endpoint they reach
  // additionally scopes its query to their own rows.
  'reseller',
] as const

export type Role = (typeof ROLES)[number]

/**
 * Permissions are `resource.action`, and read and write are always separate:
 * a support agent must be able to see an order to answer a question about it
 * without being able to refund it.
 */
export const PERMISSIONS = [
  'users.read',
  'users.write',
  'users.suspend',
  'users.impersonate',

  'admins.read',
  'admins.write',

  'packages.read',
  'packages.write',
  'orders.read',
  'orders.refund',
  'payments.read',
  'payments.approve',
  'wallet.read',
  'wallet.adjust',

  'panels.read',
  'panels.write',
  'subscriptions.read',
  'subscriptions.write',

  'tickets.read',
  'tickets.reply',
  'tickets.assign',

  'broadcast.read',
  'broadcast.send',
  'campaigns.write',

  'analytics.view',
  'analytics.export',

  'resellers.read',
  'resellers.write',

  'audit.read',
  'settings.read',
  'settings.write',
  'metrics.read',
] as const

export type Permission = (typeof PERMISSIONS)[number]

export const ROLE_LABEL_FA: Record<Role, string> = {
  super_admin: 'مالک',
  admin: 'مدیر',
  finance: 'مالی',
  support: 'پشتیبانی',
  viewer: 'ناظر',
  reseller: 'نماینده',
}

export const ROLE_DESCRIPTION_FA: Record<Role, string> = {
  super_admin:
    'دسترسی کامل، شامل ساخت مدیر و تغییر تنظیمات',
  admin:
    'همه‌چیز به‌جز ساخت مدیر، تنظیمات حساس و جای کاربر نشستن',
  finance:
    'سفارش‌ها، پرداخت‌ها، کیف پول و گزارش‌ها',
  support:
    'تیکت‌ها، سرویس‌ها و مشاهده‌ی اطلاعات کاربر',
  viewer:
    'فقط خواندن، بدون هیچ تغییری',
  reseller:
    'فقط مشتری‌ها و سرویس‌های خودش، با قیمت و اعتبار اختصاصی',
}

/**
 * What each role holds, mirroring `_ROLE_PERMISSIONS` in the API.
 *
 * Used only to *describe* roles on the permissions screen - "what would this
 * person be able to do?" - never to authorise the operator in front of us.
 * That is what their own issued list is for, and the two can differ: an
 * operator may carry explicit overrides on top of their role.
 */
const READ_ONLY = PERMISSIONS.filter((p) => p.endsWith('.read'))

const ROLE_PERMISSIONS: Record<Role, readonly Permission[]> = {
  super_admin: PERMISSIONS,
  admin: PERMISSIONS.filter(
    (p) => !(['admins.write', 'settings.write', 'users.impersonate'] as string[]).includes(p),
  ),
  finance: [
    'users.read',
    'orders.read',
    'orders.refund',
    'payments.read',
    'payments.approve',
    'wallet.read',
    'wallet.adjust',
    'packages.read',
    'metrics.read',
    'analytics.view',
    'analytics.export',
  ],
  support: [
    'users.read',
    'users.suspend',
    'orders.read',
    'payments.read',
    'packages.read',
    'subscriptions.read',
    'subscriptions.write',
    'tickets.read',
    'tickets.reply',
    'tickets.assign',
  ],
  // Derived from the `.read` suffix, minus the audit trail, plus analytics -
  // which does not end in `.read` and would otherwise be missing.
  viewer: [...READ_ONLY.filter((p) => p !== 'audit.read'), 'analytics.view'],
  // Deliberately small, and deliberately not derived from the `.read` suffix:
  // a reseller must not pick up `admins.read` or `settings.read` by the
  // accident of a naming convention. Every one of these is additionally scoped
  // to their own rows by the API - `users.read` means "the customers I
  // created", which a permission list cannot express.
  reseller: [
    'users.read',
    'packages.read',
    'subscriptions.read',
    'subscriptions.write',
    'orders.read',
    'wallet.read',
    'tickets.read',
    'tickets.reply',
  ],
}

/**
 * Does the signed-in operator hold this permission?
 *
 * Takes the list the API issued for them, not their role: an operator can
 * carry explicit grants and revocations on top of the role's defaults, and the
 * server has already resolved all of that.
 */
export function can(held: readonly string[] | null | undefined, permission: Permission): boolean {
  if (!held) return false
  return held.includes(permission)
}

/** True when the operator holds at least one of the permissions. */
export function canAny(
  held: readonly string[] | null | undefined,
  permissions: readonly Permission[],
): boolean {
  return permissions.some((permission) => can(held, permission))
}

/** True only when the operator holds every permission. */
export function canAll(
  held: readonly string[] | null | undefined,
  permissions: readonly Permission[],
): boolean {
  return permissions.every((permission) => can(held, permission))
}

/** What a role holds by default. For describing roles, not for authorising. */
export function permissionsFor(role: Role): readonly Permission[] {
  return ROLE_PERMISSIONS[role] ?? []
}

/**
 * Roles ordered from most to least privileged, used to render the permission
 * matrix and to stop an operator from assigning a role above their own.
 *
 * `finance` and `support` deliberately share a rank: neither may promote the
 * other, and neither may promote itself. Only a strictly higher rank assigns.
 */
export const ROLE_RANK: Record<Role, number> = {
  super_admin: 4,
  admin: 3,
  finance: 2,
  support: 2,
  viewer: 1,
  // Zero, so nobody can be promoted *to* reseller from the admins screen and
  // no reseller can assign anything. A reseller account is created through the
  // resellers screen, which also creates the prices, credit and panels that
  // make the role mean anything.
  reseller: 0,
}

/**
 * An operator may only assign a role strictly below their own rank.
 *
 * Without this, an admin can promote a colleague to admin, and the role
 * boundary stops meaning anything after the first friendly favour. The API
 * enforces the same rule; this only keeps the UI from offering what the server
 * would refuse.
 */
export function canAssignRole(
  actor: Role,
  target: Role,
  held: readonly string[] | null | undefined,
): boolean {
  // `reseller` is never assignable here whoever is asking: the role without a
  // reseller record beside it is an account that signs in and can then do
  // nothing, which is a worse outcome than refusing.
  if (target === 'reseller') return false
  if (actor === 'super_admin') return target !== 'super_admin'
  if (!can(held, 'admins.write')) return false
  return ROLE_RANK[actor] > ROLE_RANK[target]
}

