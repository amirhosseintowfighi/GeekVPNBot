/**
 * Catalogue slugs: the URL-safe id under a category, product or campaign.
 *
 * The API accepts lowercase Latin, digits and single hyphens, up to 64
 * characters (`domain/catalog/slug.py`). The field used to refuse anything
 * else as it was typed - a space did nothing at all - and was required, so an
 * operator naming a category in Persian had to invent an English id first.
 * Now a space becomes a hyphen, what cannot be in a slug is dropped, and an
 * empty field is filled in on save.
 */

export const MAX_SLUG = 64

/** Shape what is being typed. A trailing hyphen stays: the next word follows. */
export function editSlug(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-/, '')
    .slice(0, MAX_SLUG)
}

/**
 * The slug to send. What was typed if it is usable, else one made from a
 * Latin name, else `<prefix>-<6 random>` for a name in Persian - nobody reads
 * that id, it only has to be unique.
 */
export function slugToSave(
  typed: string,
  name: string,
  prefix: string,
  maxLength: number = MAX_SLUG,
): string {
  const tidy = (value: string) =>
    editSlug(value).slice(0, maxLength).replace(/-+$/, '')
  const fromTyped = tidy(typed)
  if (fromTyped.length >= 2) return fromTyped
  const fromName = tidy(name)
  if (fromName.length >= 2) return fromName
  const random = Math.random().toString(36).slice(2, 8).padEnd(6, '0')
  return `${prefix}-${random}`
}
