/**
 * `<Button asChild>` must hand Radix's Slot exactly one child.
 *
 * Slot runs React.Children.only. Rendering a spinner slot next to the child -
 * even a null one - makes that two children, and the throw happens during the
 * first client render, so the whole Mini App shows Next's generic
 * "Application error" instead of a screen.
 */

import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Button } from '@/components/ui/button'

describe('Button', () => {
  it('renders a link child without throwing when asChild is set', () => {
    render(
      <Button asChild>
        <a href="/shop">فروشگاه</a>
      </Button>,
    )

    expect(screen.getByRole('link', { name: 'فروشگاه' })).toBeDefined()
  })

  it('still shows its spinner when it renders its own button', () => {
    const { container } = render(<Button loading>ثبت</Button>)

    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()
    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })
})
