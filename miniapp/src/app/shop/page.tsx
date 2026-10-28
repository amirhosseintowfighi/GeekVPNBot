'use client'

import * as React from 'react'
import useSWR from 'swr'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { VolumeCard } from '@/components/feature/volume-card'
import { SkeletonList } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ApiError, fetcher } from '@/lib/api'
import { haptic } from '@/lib/telegram'
import type { Storefront } from '@/lib/types'

/**
 * The shop.
 *
 * Categories are tabs, products - the volumes - are cards, and a product's
 * packages - its terms - are the next screen. That is the bot's own order
 * (volume, then months), and keeping it identical means the support team can
 * describe a path once and have it work in both places.
 *
 * Each step is a route rather than a sheet, so Telegram's back button walks
 * back through them.
 */
export default function ShopPage() {
  const { data, error, mutate } = useSWR<Storefront>(
    '/api/miniapp/storefront',
    fetcher,
  )

  if (error instanceof ApiError && !data) {
    return (
      <>
        <PageHeader title={'\u0641\u0631\u0648\u0634\u06af\u0627\u0647'} back={false} />
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      </>
    )
  }

  if (!data) {
    return (
      <>
        <PageHeader title={'\u0641\u0631\u0648\u0634\u06af\u0627\u0647'} back={false} />
        <SkeletonList count={4} />
      </>
    )
  }

  const categories = data.categories.filter((c) => c.products.length > 0)

  if (categories.length === 0) {
    return (
      <>
        <PageHeader title={'\u0641\u0631\u0648\u0634\u06af\u0627\u0647'} back={false} />
        <EmptyState
          title={'\u0641\u0639\u0644\u0627\u064b \u0628\u0633\u062a\u0647\u200c\u0627\u06cc \u0628\u0631\u0627\u06cc \u0641\u0631\u0648\u0634 \u0646\u06cc\u0633\u062a'}
          description={'\u0628\u0647\u200c\u0632\u0648\u062f\u06cc \u0628\u0633\u062a\u0647\u200c\u0647\u0627\u06cc \u062c\u062f\u06cc\u062f \u0627\u0636\u0627\u0641\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
        />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={'\u0641\u0631\u0648\u0634\u06af\u0627\u0647'}
        subtitle={'\u0627\u0648\u0644 \u062d\u062c\u0645\u060c \u0628\u0639\u062f \u0645\u062f\u062a \u0632\u0645\u0627\u0646'}
        back={false}
      />

      <Tabs defaultValue={categories[0]!.categoryId} className="pb-4">
        {categories.length > 1 ? (
          <TabsList className="no-scrollbar overflow-x-auto">
            {categories.map((category) => (
              <TabsTrigger
                key={category.categoryId}
                value={category.categoryId}
                onClick={haptic.select}
              >
                {category.icon ? (
                  <span aria-hidden>{category.icon}</span>
                ) : null}
                {category.nameFa}
              </TabsTrigger>
            ))}
          </TabsList>
        ) : null}

        {categories.map((category) => (
          <TabsContent
            key={category.categoryId}
            value={category.categoryId}
            className="space-y-3"
          >
            {category.products
              .filter((product) => product.plans.length > 0)
              .map((product) => (
                <VolumeCard
                  key={product.productId}
                  product={product}
                  href={`/shop/p/${product.productId}`}
                />
              ))}
          </TabsContent>
        ))}
      </Tabs>
    </>
  )
}
