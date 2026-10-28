'use client'

import Link from 'next/link'
import { ChevronLeft } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { priceFrom, termsOf } from '@/lib/plans'
import { haptic } from '@/lib/telegram'
import type { ProductCard } from '@/lib/types'

/**
 * The first step of buying: a volume, before any term.
 *
 * Products are the volumes - "20GB", "50GB" - and their packages are the
 * terms, the same two steps the bot asks in. Listing every package of every
 * product on one screen made a customer compare twelve prices at once to
 * answer what is really two small questions.
 */
export function VolumeCard({ product, href }: { product: ProductCard; href: string }) {
  const from = priceFrom(product)

  return (
    <Link href={href} onClick={haptic.select} className="block rounded-3xl active:scale-[0.99]">
      <Card className="flex items-center gap-3 p-4">
        <span className="icon-tile size-12 rounded-2xl text-xl" aria-hidden>
          {product.icon ?? '🚀'}
        </span>

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-base font-extrabold">{product.nameFa}</p>
            {product.badgeFa ? (
              <Badge variant="brand" className="shrink-0">
                {product.badgeFa}
              </Badge>
            ) : null}
          </div>
          {product.taglineFa ? (
            <p className="text-xs leading-relaxed text-muted-foreground">{product.taglineFa}</p>
          ) : null}
          <p className="nums text-xs text-muted-foreground">{termsOf(product)}</p>
          {from ? <p className="nums text-sm font-extrabold">{from}</p> : null}
        </div>

        <ChevronLeft className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      </Card>
    </Link>
  )
}
