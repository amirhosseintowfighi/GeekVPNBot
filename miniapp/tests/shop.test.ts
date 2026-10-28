import { describe, expect, it } from 'vitest'

import { resolveShop, THEME_BOOTSTRAP } from '@/lib/shop'

const SHOP = '0123456789abcdef0123456789abcdef'

/**
 * A reseller's bot opens the app with `?shop=`. The app's own navigation
 * drops the query, so a later screen has to find it in sessionStorage - or
 * it would sign the customer into our shop instead of theirs.
 */
describe('resolveShop', () => {
  it('reads the shop from the address the bot opened', () => {
    expect(resolveShop(`?shop=${SHOP}`, null)).toBe(SHOP)
  })

  it('keeps it after the query is gone', () => {
    expect(resolveShop('', SHOP)).toBe(SHOP)
  })

  it('is our own app without one', () => {
    expect(resolveShop('', null)).toBeNull()
  })

  it('ignores anything that is not a shop id', () => {
    expect(resolveShop('?shop=<script>', null)).toBeNull()
    expect(resolveShop('', 'nope')).toBeNull()
  })

  it('the head script uses the same storage key and id rule', () => {
    expect(THEME_BOOTSTRAP).toContain("'geek.shop'")
    expect(THEME_BOOTSTRAP).toContain('/^[0-9a-f]{32}$/')
  })
})
