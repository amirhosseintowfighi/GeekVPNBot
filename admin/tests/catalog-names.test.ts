import { describe, expect, it } from 'vitest'

import { normalizeName, normalizeSearch } from '@/lib/fa'
import { editSlug, slugToSave } from '@/lib/slug'

/**
 * Names and slugs in the catalogue.
 *
 * Reported: a category could not be given a name with a space in it, and the
 * "شناسه" field seemed to cap what could be typed. Two causes. The rename
 * dialog cleaned names with `normalizeInput`, which exists to make *numbers*
 * parseable and deletes every space - "اروپا غربی" was saved "اروپاغربی".
 * And the slug field took only lowercase Latin, digits and single hyphens,
 * refused a space outright, and was required.
 */
describe('normalizeName', () => {
  it('keeps the spaces inside a name', () => {
    expect(normalizeName('  اروپا   غربی ')).toBe('اروپا غربی')
  })

  it('keeps Persian digits as typed: "۲۰ گیگ" is a name, not a number', () => {
    expect(normalizeName('۲۰ گیگ')).toBe('۲۰ گیگ')
  })
})

describe('normalizeSearch', () => {
  it('keeps the space between two words of a search', () => {
    expect(normalizeSearch(' amir  hossein ')).toBe('amir hossein')
  })

  it('still reads Persian digits as Latin ones', () => {
    expect(normalizeSearch('۰۹۱۲')).toBe('0912')
  })
})

describe('editSlug', () => {
  it('turns a space into a hyphen instead of refusing it', () => {
    expect(editSlug('Europe West')).toBe('europe-west')
  })

  it('drops what a slug cannot hold rather than blocking the keyboard', () => {
    expect(editSlug('geek_turbo!!')).toBe('geek-turbo')
    expect(editSlug('اروپا')).toBe('')
  })

  it('lets a trailing hyphen stand while the next word is being typed', () => {
    expect(editSlug('europe ')).toBe('europe-')
  })
})

describe('slugToSave', () => {
  it('uses what was typed when it is a slug', () => {
    expect(slugToSave('europe-west-', 'اروپا', 'cat')).toBe('europe-west')
  })

  it('falls back to a Latin name', () => {
    expect(slugToSave('', 'Gaming Pro', 'cat')).toBe('gaming-pro')
  })

  it('makes one up for a Persian name, so the field can be left empty', () => {
    expect(slugToSave('', 'اروپا غربی', 'cat')).toMatch(/^cat-[a-z0-9]{6}$/)
  })

  it('never sends more than the column holds', () => {
    expect(slugToSave('a'.repeat(100), '', 'cat')).toHaveLength(64)
  })
})
