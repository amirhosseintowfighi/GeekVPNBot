import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import { isPublicRoute, permissionForPath } from '@/lib/nav'

/**
 * Every page in the app must resolve to a permission.
 *
 * The route guard denies anything the navigation table does not cover, and it
 * is right to: a screen missing from that table is a bug, not a door to leave
 * open. The consequence is that adding a page and forgetting the table shows
 * "your role does not have access" - to everyone, including an owner holding
 * every permission there is. The message is true about the route and false
 * about the person, which is why it sent an owner looking for whoever has more
 * access than they do.
 *
 * Detail routes inherit their parent's entry by prefix, so this walks the real
 * `app/` directory rather than a list somebody has to remember to update.
 */

const APP = path.resolve(__dirname, '../src/app')

/** `app/users/[userId]/page.tsx` -> `/users/abc`. Dynamic segments are given
 *  a concrete value so prefix matching is exercised the way it runs. */
function routes(dir: string, prefix = ''): string[] {
  const found: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const segment = entry.name.startsWith('[') ? 'sample-id' : entry.name
      found.push(...routes(path.join(dir, entry.name), `${prefix}/${segment}`))
    } else if (entry.name === 'page.tsx') {
      found.push(prefix === '' ? '/' : prefix)
    }
  }
  return found
}

describe('the route guard', () => {
  const all = routes(APP)

  it('finds the pages', () => {
    expect(all.length).toBeGreaterThan(5)
    expect(all).toContain('/')
  })

  it('resolves a permission for every one of them', () => {
    // Sign-in renders outside the frame and before there is a session to check.
    // `/sign-in` and `/set-password` exist before an operator does: both are
    // opened by somebody with no session and no permissions, and a guard that
    // refused them would refuse the two doors into the panel.
    const guarded = all.filter((route) => !isPublicRoute(route))
    const unmapped = guarded.filter((route) => permissionForPath(route) === null)

    expect(unmapped).toEqual([])
  })
})
