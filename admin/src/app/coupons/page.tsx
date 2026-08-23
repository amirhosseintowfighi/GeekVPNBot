'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Copy, Layers, Plus } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDate, faNumber, normalizeInput } from '@/lib/fa'
import type { CouponRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader, Toolbar } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Progress } from '@/components/ui/primitives'

/**
 * Coupons.
 *
 * Bulk creation is the feature that matters here: influencer campaigns need
 * hundreds of single-use codes, and generating them one at a time is how
 * duplicates and typos get into the catalogue. The prefix is uppercased and
 * ASCII-only because a Persian coupon code cannot be typed reliably on a
 * Latin keyboard, and customers will be pasting these from Telegram.
 *
 * Codes are archived, never deleted. A deleted code loses its usage history,
 * and the first question after a suspicious spike is always "who used it".
 */
export default function CouponsPage() {
  const { can } = useSession()
  const [state, setState] = React.useState<string | undefined>('active')
  const [bulkOpen, setBulkOpen] = React.useState(false)

  const { data, error, isLoading, mutate } = useSWR<CouponRow[]>(
    ['coupons', state],
    () => api.coupons({ state }),
  )

  if (!can('packages.read')) return <ForbiddenState permission="packages.read" />

  return (
    <>
      <PageHeader
        title={'\u06a9\u062f\u0647\u0627\u06cc \u062a\u062e\u0641\u06cc\u0641'}
        description={'\u0633\u0627\u062e\u062a\u060c \u0645\u062d\u062f\u0648\u062f\u06cc\u062a \u0648 \u0645\u0635\u0631\u0641 \u06a9\u062f\u0647\u0627'}
        actions={
          can('packages.write') ? (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setBulkOpen(true)}>
                <Layers className="size-3.5" aria-hidden />
                {'\u0633\u0627\u062e\u062a \u06af\u0631\u0648\u0647\u06cc'}
              </Button>
              <Button>
                <Plus className="size-3.5" aria-hidden />
                {'\u06a9\u062f \u062c\u062f\u06cc\u062f'}
              </Button>
            </div>
          ) : null
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => mutate()}
        />
      ) : null}

      <Card>
        <Toolbar>
          <FilterSelect
            value={state}
            onChange={setState}
            options={[
              { value: 'active', label: '\u0641\u0639\u0627\u0644' },
              { value: 'archived', label: '\u0628\u0627\u06cc\u06af\u0627\u0646\u06cc' },
              { value: 'expired', label: '\u0645\u0646\u0642\u0636\u06cc' },
            ]}
            allLabel={'\u0647\u0645\u0647'}
          />
        </Toolbar>

        {isLoading && !data ? (
          <SkeletonTable rows={8} cols={6} />
        ) : !data || data.length === 0 ? (
          <EmptyState title={'\u06a9\u062f\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f'} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u06a9\u062f'}</TableHead>
                <TableHead>{'\u062a\u062e\u0641\u06cc\u0641'}</TableHead>
                <TableHead>{'\u0645\u0635\u0631\u0641'}</TableHead>
                <TableHead>{'\u0633\u0642\u0641 \u0647\u0631 \u06a9\u0627\u0631\u0628\u0631'}</TableHead>
                <TableHead>{'\u0627\u0639\u062a\u0628\u0627\u0631 \u062a\u0627'}</TableHead>
                <TableHead>{'\u0642\u0627\u0628\u0644 \u062a\u062c\u0645\u06cc\u0639'}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((coupon) => {
                // The API already formats the discount - "\u06f2\u06f0\u066a" or
                // "\u06f5\u06f0\u066c\u06f0\u06f0\u06f0 \u062a\u0648\u0645\u0627\u0646" - because whether a coupon is a percentage
                // or a fixed amount is a domain detail the panel should not be
                // re-deriving from a bps field that is not in the payload.
                const limited = coupon.maxRedemptions !== null
                const fraction = limited
                  ? Math.min(1, coupon.redemptionCount / Math.max(1, coupon.maxRedemptions ?? 1))
                  : 0
                return (
                  <TableRow key={coupon.id}>
                    <TableCell>
                      <span dir="ltr" className="font-mono text-2xs">{coupon.code}</span>
                    </TableCell>
                    <TableCell numeric>{coupon.discountLabel}</TableCell>
                    <TableCell>
                      {limited ? (
                        <div className="min-w-24 space-y-1">
                          <Progress value={fraction * 100} />
                          <span className="nums text-2xs text-muted-foreground">
                            {faNumber(coupon.redemptionCount) +
                              ' / ' +
                              faNumber(coupon.maxRedemptions ?? 0)}
                          </span>
                        </div>
                      ) : (
                        <span className="nums text-muted-foreground">
                          {faNumber(coupon.redemptionCount)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell numeric>{faNumber(coupon.maxPerUser)}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {coupon.endsAt ? faDate(coupon.endsAt) : '\u0628\u062f\u0648\u0646 \u0627\u0646\u0642\u0636\u0627'}
                    </TableCell>
                    <TableCell>
                      {/* Stacking is a money decision, so it is stated plainly
                          rather than hidden behind a settings page. */}
                      <Badge variant={coupon.stacksWithCampaign ? 'warning' : 'muted'}>
                        {coupon.stacksWithCampaign ? '\u0628\u0644\u0647' : '\u062e\u06cc\u0631'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {can('packages.write') && coupon.state !== 'archived' ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={async () => {
                            await api.archiveCoupon(coupon.id)
                            mutate()
                          }}
                        >
                          {'\u0628\u0627\u06cc\u06af\u0627\u0646\u06cc'}
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

      <BulkDialog open={bulkOpen} onClose={() => setBulkOpen(false)} onDone={() => mutate()} />
    </>
  )
}

function BulkDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  const [prefix, setPrefix] = React.useState('')
  const [count, setCount] = React.useState('50')
  const [discount, setDiscount] = React.useState('20')
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)
  const [created, setCreated] = React.useState<string[] | null>(null)

  // ASCII only, uppercase: these get typed by customers on Latin keyboards.
  const cleanPrefix = prefix.toUpperCase().replace(/[^A-Z0-9]/g, '')
  const parsedCount = Number(normalizeInput(count).replace(/\D/g, '')) || 0
  const parsedDiscount = Number(normalizeInput(discount).replace(/\D/g, '')) || 0
  const valid = cleanPrefix.length >= 2 && parsedCount > 0 && parsedCount <= 1000 && parsedDiscount > 0 && parsedDiscount <= 70

  const submit = async () => {
    setBusy(true)
    setFailure(null)
    try {
      // The endpoint takes a whole coupon template, not a loose discount:
      // it is creating real coupons, and each needs a kind and a value.
      const response = await api.bulkCreateCoupons({
        prefix: cleanPrefix,
        count: parsedCount,
        template: {
          code: cleanPrefix,
          kind: 'promotional',
          discountKind: 'percentage',
          discountValue: parsedDiscount,
          maxPerUser: 1,
          maxRedemptions: 1,
        },
      })
      setCreated(response.map((coupon) => coupon.code))
      onDone()
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  const close = () => {
    setCreated(null)
    setFailure(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : close())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{'\u0633\u0627\u062e\u062a \u06af\u0631\u0648\u0647\u06cc \u06a9\u062f \u062a\u062e\u0641\u06cc\u0641'}</DialogTitle>
          <DialogDescription>
            {'\u0647\u0631 \u06a9\u062f \u06cc\u06a9\u200c\u0628\u0627\u0631 \u0645\u0635\u0631\u0641 \u0627\u0633\u062a \u0648 \u0628\u0627 \u067e\u06cc\u0634\u0648\u0646\u062f \u0627\u0646\u062a\u062e\u0627\u0628\u06cc \u0634\u0645\u0627 \u0633\u0627\u062e\u062a\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          {created ? (
            <>
              <p className="rounded-md border border-success/30 bg-success/10 px-3 py-2 text-2xs text-success">
                {faNumber(created.length) + ' \u06a9\u062f \u0633\u0627\u062e\u062a\u0647 \u0634\u062f.'}
              </p>
              <div
                dir="ltr"
                className="max-h-56 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-2xs"
              >
                {created.join('\n')}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigator.clipboard?.writeText(created.join('\n'))}
              >
                <Copy className="size-3.5" aria-hidden />
                {'\u06a9\u067e\u06cc \u0647\u0645\u0647'}
              </Button>
            </>
          ) : (
            <>
              <Field
                label={'\u067e\u06cc\u0634\u0648\u0646\u062f'}
                hint={'\u0641\u0642\u0637 \u062d\u0631\u0648\u0641 \u0644\u0627\u062a\u06cc\u0646 \u0648 \u0639\u062f\u062f'}
              >
                <Input ltr value={prefix} onChange={(event) => setPrefix(event.target.value)} autoFocus />
              </Field>

              <Field label={'\u062a\u0639\u062f\u0627\u062f'} hint={'\u062d\u062f\u0627\u06a9\u062b\u0631 \u06f1\u06f0\u06f0\u06f0'}>
                <Input ltr inputMode="numeric" value={count} onChange={(event) => setCount(event.target.value)} />
              </Field>

              <Field
                label={'\u062f\u0631\u0635\u062f \u062a\u062e\u0641\u06cc\u0641'}
                hint={'\u062d\u062f\u0627\u06a9\u062b\u0631 \u06f7\u06f0 \u062f\u0631\u0635\u062f (\u0633\u0642\u0641 \u0633\u06cc\u0627\u0633\u062a \u0642\u06cc\u0645\u062a\u200c\u06af\u0630\u0627\u0631\u06cc)'}
              >
                <Input ltr inputMode="numeric" value={discount} onChange={(event) => setDiscount(event.target.value)} />
              </Field>

              {cleanPrefix ? (
                <p className="text-2xs text-muted-foreground">
                  {'\u0646\u0645\u0648\u0646\u0647: '}
                  <span dir="ltr" className="font-mono">{cleanPrefix + '-A1B2C3'}</span>
                </p>
              ) : null}

              {failure ? (
                <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
                  {failure}
                </p>
              ) : null}
            </>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={close} disabled={busy}>
            {created ? '\u0628\u0633\u062a\u0646' : '\u0627\u0646\u0635\u0631\u0627\u0641'}
          </Button>
          {!created ? (
            <Button loading={busy} disabled={!valid} onClick={submit}>
              {'\u0633\u0627\u062e\u062a'}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
