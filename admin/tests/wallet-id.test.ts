import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * The wallet is addressed by Telegram id, never by the customer's UUID.
 *
 * The user detail page passed the route parameter - a UUID - to
 * `/admin/wallets/{userId}`, where the API declares `user_id: int`. Every call
 * was rejected as invalid before it reached the ledger: the balance rendered
 * as an em dash forever and no adjustment ever applied. Nothing failed loudly,
 * because a missing balance and a rejected one look identical on screen.
 *
 * Checked against the source rather than by rendering, because what went wrong
 * is which variable was passed, and that is visible right here.
 */

const PAGE = path.resolve(__dirname, '../src/app/users/[userId]/page.tsx')

describe('the user detail page', () => {
  const source = fs.readFileSync(PAGE, 'utf8')

  it('addresses the wallet by Telegram id', () => {
    const calls = source.match(/api\.(walletBalance|adjustWallet)\([^)]*/g) ?? []

    expect(calls.length).toBeGreaterThan(0)
    for (const call of calls) {
      expect(call).toContain('telegramId')
      expect(call).not.toMatch(/\(\s*userId\b/)
    }
  })

  it('addresses the customer by their UUID when writing to them', () => {
    const call = source.match(/api\.messageCustomer\([^)]*/)?.[0]

    expect(call).toBeDefined()
    expect(call).toContain('userId')
  })
})
