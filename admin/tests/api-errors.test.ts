import { describe, expect, it } from 'vitest'

import { ApiError } from '@/lib/api'

/**
 * What a rejected request tells the operator.
 *
 * A 422 rendered as "اطلاعات واردشده درست نیست" and nothing else. That is a
 * dead end when the form looks correct - and worse when the rejected field is
 * not on the form at all: a missing `Idempotency-Key` header fails exactly the
 * same way, and no amount of re-reading the inputs will show it.
 *
 * The parsing lives inside `request`, which needs a Response, so these test the
 * shape the screens rely on rather than reaching through the module.
 */
describe('ApiError', () => {
  it('carries the fields a 422 named', () => {
    const error = new ApiError(422, 'اطلاعات واردشده درست نیست (header.Idempotency-Key)', [
      'header.Idempotency-Key',
    ])

    expect(error.status).toBe(422)
    expect(error.fields).toEqual(['header.Idempotency-Key'])
  })

  it('has no fields for the statuses that do not name one', () => {
    expect(new ApiError(401, 'x').fields).toEqual([])
    expect(new ApiError(0, 'x').fields).toEqual([])
  })

  it('keeps the Persian message readable when fields are appended', () => {
    const error = new ApiError(422, 'اطلاعات واردشده درست نیست (titleFa، bodyFa)', [
      'titleFa',
      'bodyFa',
    ])

    // The separator is the Persian comma: an operator reads this, not a parser.
    expect(error.messageFa).toContain('، ')
  })
})
