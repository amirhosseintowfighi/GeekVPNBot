'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, StaggerItem, StaggerList } from '@/components/shell/states'
import { PlanCard } from '@/components/feature/plan-card'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { SkeletonList } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ApiError, fetcher } from '@/lib/api'
import { haptic } from '@/lib/telegram'
import type { Storefront } from '@/lib/types'

/**
 * The shop.
 *
 * Categories are tabs, products are sections, plans are cards. That is the
 * same three-level shape the bot uses, and keeping it identical means the
 * support team can describe a path once and have it work in both places.
 *
 * A plan tap routes to the review screen rather than opening a sheet, because
 * checkout has several steps and each one deserves a back button.
 */
export default function ShopPage() {
  const router = useRouter()
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
        subtitle={'\u0628\u0633\u062a\u0647\u200c\u0627\u06cc \u0631\u0627 \u06a9\u0647 \u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u06cc\u062f \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f'}
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
            className="space-y-6"
          >
            {category.products.map((product) => (
              <section key={product.productId} className="space-y-3">
                <Card className="space-y-2 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="flex items-center gap-2 text-sm font-semibold">
                        {product.icon ? (
                          <span aria-hidden>{product.icon}</span>
                        ) : null}
                        <span className="truncate">{product.nameFa}</span>
                      </h2>
                      {product.taglineFa ? (
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                          {product.taglineFa}
                        </p>
                      ) : null}
                    </div>
                    {product.badgeFa ? (
                      <Badge variant="brand" className="shrink-0">
                        {product.badgeFa}
                      </Badge>
                    ) : null}
                  </div>

                  {product.featuresFa.length > 0 ? (
                    <ul className="flex flex-wrap gap-1.5 pt-1">
                      {product.featuresFa.map((feature) => (
                        <li key={feature}>
                          <Badge variant="muted" className="font-normal">
                            {feature}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </Card>

                {/*
                  Two columns from the small breakpoint up. On a phone a single
                  column keeps the price readable at a glance; cramming two
                  cards side by side is where the toman figure starts wrapping.
                */}
                <StaggerList className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {product.plans.map((plan) => (
                    <StaggerItem key={plan.planId}>
                      <PlanCard
                        plan={plan}
                        onSelect={() => router.push(`/shop/${plan.planId}`)}
                      />
                    </StaggerItem>
                  ))}
                </StaggerList>
              </section>
            ))}
          </TabsContent>
        ))}
      </Tabs>
    </>
  )
}
