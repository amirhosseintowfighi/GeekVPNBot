'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Plus, Wand2 } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faNumber, gib, normalizeInput, percent, toman } from '@/lib/fa'
import { PLAN_TYPE, PUBLICATION_STATE } from '@/lib/labels'
import type { CategoryRow, DurationRung, PlanRow, ProductRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { FilterSelect } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/**
 * Products and plans.
 *
 * The important thing on this screen is the ladder generator. Pricing a
 * 7/30/90/180/365 ladder by hand is where mistakes get made - an operator
 * types 90-day prices that are worse value than 30-day, and the catalogue
 * quietly punishes the customers who commit longest.
 *
 * So the ladder is generated from a single monthly price by the same
 * `DurationLadderService` the domain already owns, with the same concave
 * discount curve (weekly priced 15% ABOVE monthly, 365-day at 25% off).
 * Generated plans land in DRAFT: nothing reaches a customer until a human
 * publishes it.
 */
export default function ProductsPage() {
  const { can } = useSession()
  const [categoryId, setCategoryId] = React.useState<string | undefined>(undefined)
  const [selectedProduct, setSelectedProduct] = React.useState<string | null>(null)
  const [ladderFor, setLadderFor] = React.useState<ProductRow | null>(null)

  const categories = useSWR<CategoryRow[]>('categories', () => api.categories())
  const products = useSWR<ProductRow[]>(['products', categoryId], () => api.products({ categoryId }))
  const plans = useSWR<PlanRow[]>(
    selectedProduct ? ['plans', selectedProduct] : null,
    () => api.plans(selectedProduct as string),
  )

  if (!can('packages.read')) return <ForbiddenState permission="packages.read" />

  const error = products.error ?? categories.error

  return (
    <>
      <PageHeader
        title={'\u0645\u062d\u0635\u0648\u0644\u0627\u062a \u0648 \u067e\u0644\u0646\u200c\u0647\u0627'}
        description={'\u062f\u0633\u062a\u0647\u200c\u0647\u0627\u060c \u0645\u062d\u0635\u0648\u0644\u0627\u062a \u0648 \u0646\u0631\u062f\u0628\u0627\u0646 \u0645\u062f\u062a\u200c\u0632\u0645\u0627\u0646'}
        actions={
          can('packages.write') ? (
            <Button>
              <Plus className="size-3.5" aria-hidden />
              {'\u0645\u062d\u0635\u0648\u0644 \u062c\u062f\u06cc\u062f'}
            </Button>
          ) : null
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => products.mutate()}
        />
      ) : null}

      <Card>
        <Toolbar>
          <FilterSelect
            value={categoryId}
            onChange={setCategoryId}
            options={(categories.data ?? []).map((category) => ({
              value: category.id,
              label: category.nameFa,
            }))}
            allLabel={'\u0647\u0645\u0647\u0654 \u062f\u0633\u062a\u0647\u200c\u0647\u0627'}
          />
        </Toolbar>

        {products.isLoading && !products.data ? (
          <SkeletonTable rows={6} cols={5} />
        ) : !products.data || products.data.length === 0 ? (
          <EmptyState
            title={'\u0645\u062d\u0635\u0648\u0644\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647'}
            description={'\u0627\u0628\u062a\u062f\u0627 \u06cc\u06a9 \u0645\u062d\u0635\u0648\u0644 \u0628\u0633\u0627\u0632\u06cc\u062f\u060c \u0633\u067e\u0633 \u0646\u0631\u062f\u0628\u0627\u0646 \u067e\u0644\u0646\u200c\u0647\u0627 \u0631\u0627 \u062a\u0648\u0644\u06cc\u062f \u06a9\u0646\u06cc\u062f.'}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u0645\u062d\u0635\u0648\u0644'}</TableHead>
                <TableHead>{'\u062f\u0633\u062a\u0647'}</TableHead>
                <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                <TableHead>{'\u067e\u0646\u0644'}</TableHead>
                <TableHead>{'\u062a\u0639\u062f\u0627\u062f \u067e\u0644\u0646'}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {products.data.map((product) => {
                const stateMeta = PUBLICATION_STATE[product.state]
                return (
                  <TableRow key={product.id} selected={selectedProduct === product.id}>
                    <TableCell>
                      <button
                        type="button"
                        onClick={() => setSelectedProduct(product.id)}
                        className="text-start hover:underline"
                      >
                        {product.icon} {product.nameFa}
                      </button>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {categories.data?.find((category) => category.id === product.categoryId)
                        ?.nameFa ?? '\u2014'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={stateMeta.tone} dot>
                        {stateMeta.fa}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {product.nodeId ?? '\u0645\u062a\u0635\u0644 \u0646\u0634\u062f\u0647'}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{product.tier}</TableCell>
                    <TableCell>
                      {can('packages.write') ? (
                        <Button variant="ghost" size="sm" onClick={() => setLadderFor(product)}>
                          <Wand2 className="size-3.5" aria-hidden />
                          {'\u062a\u0648\u0644\u06cc\u062f \u0646\u0631\u062f\u0628\u0627\u0646'}
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      {selectedProduct ? (
        <Card>
          <CardHeader>
            <CardTitle>{'\u067e\u0644\u0646\u200c\u0647\u0627\u06cc \u0645\u062d\u0635\u0648\u0644'}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {plans.isLoading && !plans.data ? (
              <SkeletonTable rows={5} cols={6} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{'\u0646\u0627\u0645'}</TableHead>
                    <TableHead>{'\u0646\u0648\u0639'}</TableHead>
                    <TableHead>{'\u0645\u062f\u062a'}</TableHead>
                    <TableHead>{'\u062d\u062c\u0645'}</TableHead>
                    <TableHead>{'\u0642\u06cc\u0645\u062a'}</TableHead>
                    <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                    <TableHead>{'\u0641\u0639\u0627\u0644'}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(plans.data ?? []).map((plan) => {
                    const typeMeta = PLAN_TYPE[plan.planType]
                    const stateMeta = PUBLICATION_STATE[plan.state]
                    return (
                      <TableRow key={plan.id}>
                        <TableCell>
                          {plan.nameFa}
                          {plan.badgeFa ? (
                            <Badge variant="success" className="ms-1.5">
                              {plan.badgeFa}
                            </Badge>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <Badge variant={typeMeta.tone}>{typeMeta.fa}</Badge>
                        </TableCell>
                        <TableCell numeric>
                          {faNumber(plan.durationDays) + ' \u0631\u0648\u0632'}
                        </TableCell>
                        <TableCell numeric>{gib(plan.quotaGib)}</TableCell>
                        <TableCell numeric>{toman(plan.basePrice, false)}</TableCell>
                        <TableCell>
                          <Badge variant={stateMeta.tone} dot>
                            {stateMeta.fa}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Switch
                            checked={plan.state === 'published'}
                            disabled={!can('packages.write')}
                            onCheckedChange={async (checked) => {
                              await api.setPlanState(plan.id, checked ? 'published' : 'draft')
                              plans.mutate()
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      ) : null}

      <LadderDialog
        product={ladderFor}
        onClose={() => setLadderFor(null)}
        onGenerated={() => {
          products.mutate()
          plans.mutate()
        }}
      />
    </>
  )
}

/**
 * Ladder generator.
 *
 * The preview is computed client-side from the same rungs the server uses, so
 * the operator sees the exact prices before committing. Showing the saving
 * per rung is what makes an accidentally-inverted ladder obvious.
 */
function LadderDialog({
  product,
  onClose,
  onGenerated,
}: {
  product: ProductRow | null
  onClose: () => void
  onGenerated: () => void
}) {
  const [monthly, setMonthly] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  const rungs = useSWR<DurationRung[]>('duration-ladder', () => api.durationLadder())

  const monthlyPrice = Number(normalizeInput(monthly).replace(/\D/g, '')) || 0

  // Mirrors domain/catalog/durations.py: price = monthly * months * (1 - bps/10000),
  // negative bps meaning a premium rather than a discount.
  const preview = (rungs.data ?? []).map((rung) => {
    const months = rung.days / 30
    const gross = monthlyPrice * months
    const price = Math.floor((gross * (10_000 - rung.discountBps)) / 10_000)
    return { rung, gross, price, saving: gross - price }
  })

  const submit = async () => {
    if (!product) return
    setBusy(true)
    setFailure(null)
    try {
      // The endpoint builds real plans, so it needs what a plan is made of.
      // Sending only a price produced a 422 every time.
      await api.generateLadder({
        productId: product.id,
        monthlyPrice,
        planType: 'unlimited',
        slugPrefix: product.slug,
        namePrefixFa: product.nameFa,
      })
      onGenerated()
      onClose()
      setMonthly('')
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={product !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{'\u062a\u0648\u0644\u06cc\u062f \u0646\u0631\u062f\u0628\u0627\u0646 \u0645\u062f\u062a\u200c\u0632\u0645\u0627\u0646'}</DialogTitle>
          <DialogDescription>
            {'\u0642\u06cc\u0645\u062a \u0645\u0627\u0647\u0627\u0646\u0647 \u0631\u0627 \u0648\u0627\u0631\u062f \u06a9\u0646\u06cc\u062f\u061b \u067e\u0644\u0646\u200c\u0647\u0627\u06cc \u06f7 \u062a\u0627 \u06f3\u06f6\u06f5 \u0631\u0648\u0632\u0647 \u0628\u0647 \u0635\u0648\u0631\u062a \u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633 \u0633\u0627\u062e\u062a\u0647 \u0645\u06cc\u200c\u0634\u0648\u0646\u062f.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          <Field
            label={'\u0642\u06cc\u0645\u062a \u0645\u0627\u0647\u0627\u0646\u0647 (\u062a\u0648\u0645\u0627\u0646)'}
            hint={'\u0645\u0628\u0646\u0627\u06cc \u0645\u062d\u0627\u0633\u0628\u0647\u0654 \u0647\u0645\u0647\u0654 \u067e\u0644\u0647\u200c\u0647\u0627'}
          >
            <Input
              ltr
              inputMode="numeric"
              value={monthly}
              onChange={(event) => setMonthly(event.target.value)}
              autoFocus
            />
          </Field>

          {monthlyPrice > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u0645\u062f\u062a'}</TableHead>
                  <TableHead>{'\u062a\u062e\u0641\u06cc\u0641'}</TableHead>
                  <TableHead>{'\u0642\u06cc\u0645\u062a'}</TableHead>
                  <TableHead>{'\u0635\u0631\u0641\u0647\u200c\u062c\u0648\u06cc\u06cc'}</TableHead>
                  <TableHead>{'\u0646\u0634\u0627\u0646'}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.map(({ rung, price, saving }) => (
                  <TableRow key={rung.slug}>
                    <TableCell>{faNumber(rung.days) + ' \u0631\u0648\u0632'}</TableCell>
                    <TableCell numeric>
                      {/* A negative bps is a premium, not a discount. The 7-day
                          rung is deliberately priced above a month. */}
                      <span className={rung.discountBps < 0 ? 'text-warning' : 'text-success'}>
                        {rung.discountBps < 0
                          ? '+' + percent(Math.abs(rung.discountBps) / 100)
                          : percent(rung.discountBps / 100)}
                      </span>
                    </TableCell>
                    <TableCell numeric className="font-semibold">{toman(price, false)}</TableCell>
                    <TableCell numeric className={saving < 0 ? 'text-warning' : 'text-success'}>
                      {toman(saving, false)}
                    </TableCell>
                    <TableCell>
                      {rung.badgeFa ? <Badge variant="success">{rung.badgeFa}</Badge> : '\u2014'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}

          {failure ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
              {failure}
            </p>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {'\u0627\u0646\u0635\u0631\u0627\u0641'}
          </Button>
          <Button loading={busy} disabled={monthlyPrice <= 0} onClick={submit}>
            {'\u062a\u0648\u0644\u06cc\u062f \u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633\u200c\u0647\u0627'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
