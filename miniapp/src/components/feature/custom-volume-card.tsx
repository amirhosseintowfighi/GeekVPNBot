'use client'

import Link from 'next/link'
import { ChevronLeft, SlidersHorizontal } from 'lucide-react'

import { Card } from '@/components/ui/card'
import { gib } from '@/lib/fa'
import { haptic } from '@/lib/telegram'

/** The last card in a category: any volume, not only the ones on the shelf. */
export function CustomVolumeCard({ floor, href }: { floor: number; href: string }) {
  return (
    <Link href={href} onClick={haptic.select} className="block rounded-3xl active:scale-[0.99]">
      <Card className="flex items-center gap-3 border border-dashed border-[color:var(--line)] p-4">
        <span className="icon-tile size-12 rounded-2xl" aria-hidden>
          <SlidersHorizontal className="size-5" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-base font-extrabold">{'حجم دلخواه'}</p>
          <p className="nums text-xs leading-relaxed text-muted-foreground">
            {`هر حجمی که لازم داری، از ${gib(floor)} در ماه به بالا`}
          </p>
        </div>
        <ChevronLeft className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      </Card>
    </Link>
  )
}
