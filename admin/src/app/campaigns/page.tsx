'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Plus } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { basisPoints, faDate, faNumber } from '@/lib/fa'
import type { CampaignRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/**
 * Campaigns - including flash sales.
 *
 * A campaign is an automatic discount bound to a window, so unlike a coupon
 * nobody has to type anything: it simply applies. That makes an accidentally
 * live campaign expensive, which is why:
 *
 * - The window is always shown, and a campaign that is enabled but outside
 *   its window is labelled as scheduled or finished rather than active. An
 *   operator must never have to compare two dates in their head to know
 *   whether money is currently being discounted.
 * - Flash sales are marked, because their whole point is a short window and
 *   they are the ones most likely to be left running by mistake.
 * - Revenue and discount given sit side by side. A campaign that moved a lot
 *   of volume while giving away more than it earned is the failure mode this
 *   table exists to make visible.
 */
export default function CampaignsPage() {
  const { can } = useSession()
  const [creating, setCreating] = React.useState(false)
  const { data, error, isLoading, mutate } = useSWR<CampaignRow[]>('campaigns', () => api.campaigns())

  if (!can('packages.read')) return <ForbiddenState permission="packages.read" />

  const now = Date.now()

  return (
    <>
      <PageHeader
        title={'\u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627'}
        description={'\u062a\u062e\u0641\u06cc\u0641\u200c\u0647\u0627\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 \u0648 \u0641\u0631\u0648\u0634\u200c\u0647\u0627\u06cc \u0644\u062d\u0638\u0647\u200c\u0627\u06cc'}
        actions={
          can('campaigns.write') ? (
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-3.5" aria-hidden />
              {'\u06a9\u0645\u067e\u06cc\u0646 \u062c\u062f\u06cc\u062f'}
            </Button>
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
        {isLoading && !data ? (
          <SkeletonTable rows={6} cols={7} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title={'\u06a9\u0645\u067e\u06cc\u0646\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647'}
            description={'\u06a9\u0645\u067e\u06cc\u0646 \u0628\u062f\u0648\u0646 \u0646\u06cc\u0627\u0632 \u0628\u0647 \u06a9\u062f\u060c \u062e\u0648\u062f\u06a9\u0627\u0631 \u0631\u0648\u06cc \u0642\u06cc\u0645\u062a \u0627\u0639\u0645\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u06a9\u0645\u067e\u06cc\u0646'}</TableHead>
                <TableHead>{'\u062a\u062e\u0641\u06cc\u0641'}</TableHead>
                <TableHead>{'\u0628\u0627\u0632\u0647'}</TableHead>
                <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                <TableHead>{'\u0633\u0641\u0627\u0631\u0634'}</TableHead>
                <TableHead>{'\u062a\u062e\u0641\u06cc\u0641 \u062f\u0627\u062f\u0647\u200c\u0634\u062f\u0647'}</TableHead>
                <TableHead>{'\u062f\u0631\u0622\u0645\u062f'}</TableHead>
                <TableHead>{'\u0641\u0639\u0627\u0644'}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((campaign) => {
                // The row carries a publication state and a formatted discount
                // label. It does not carry an `enabled` flag, a `discountBps`,
                // or per-campaign revenue - those live on
                // /catalog/campaigns/{id}/performance, which is a second call.
                const startsAt = campaign.startsAt ? new Date(campaign.startsAt).getTime() : null
                const endsAt = campaign.endsAt ? new Date(campaign.endsAt).getTime() : null

                // "Published" and "currently discounting" are different things.
                // The badge reports the second one.
                const published = campaign.state === 'published'
                const upcoming = startsAt !== null && startsAt > now
                const finished = endsAt !== null && endsAt < now
                const live = published && !upcoming && !finished

                const stateFa = live
                  ? '\u062f\u0631 \u062d\u0627\u0644 \u0627\u062c\u0631\u0627'
                  : upcoming
                    ? '\u0632\u0645\u0627\u0646\u200c\u0628\u0646\u062f\u06cc \u0634\u062f\u0647'
                    : finished
                      ? '\u067e\u0627\u06cc\u0627\u0646 \u06cc\u0627\u0641\u062a\u0647'
                      : '\u063a\u06cc\u0631\u0641\u0639\u0627\u0644'

                const tone = live ? 'success' : upcoming ? 'info' : finished ? 'muted' : 'outline'

                return (
                  <TableRow key={campaign.id}>
                    <TableCell>{campaign.nameFa}</TableCell>

                    <TableCell numeric>{campaign.discountLabel}</TableCell>

                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {(campaign.startsAt ? faDate(campaign.startsAt) : '\u2014') +
                        ' \u2014 ' +
                        (campaign.endsAt ? faDate(campaign.endsAt) : '\u0628\u062f\u0648\u0646 \u067e\u0627\u06cc\u0627\u0646')}
                    </TableCell>

                    <TableCell>
                      <Badge variant={tone} dot>
                        {stateFa}
                      </Badge>
                    </TableCell>

                    <TableCell numeric>{faNumber(campaign.redemptionCount)}</TableCell>
                    <TableCell numeric className="text-muted-foreground">
                      {campaign.remainingStock === null
                        ? '\u0646\u0627\u0645\u062d\u062f\u0648\u062f'
                        : faNumber(campaign.remainingStock)}
                    </TableCell>

                    <TableCell>
                      <Switch
                        checked={published}
                        disabled={!can('campaigns.write')}
                        onCheckedChange={async (checked) => {
                          await api.setCampaignState(campaign.id, checked ? 'activate' : 'pause')
                          mutate()
                        }}
                      />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <CampaignDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => mutate()}
      />
    </>
  )
}

/**
 * Creating a campaign.
 *
 * A campaign discounts automatically, with no code to type - which is exactly
 * why it starts paused. The table beside this exists to make a campaign that
 * gives away more than it earns visible; one that starts running the moment it
 * is created would do that giving before anyone had looked at it.
 */
function CampaignDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [slug, setSlug] = React.useState('')
  const [nameFa, setNameFa] = React.useState('')
  const [kind, setKind] = React.useState('seasonal')
  const [discountKind, setDiscountKind] = React.useState<'percentage' | 'fixed_amount'>('percentage')
  const [value, setValue] = React.useState('15')
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  const parsedValue = Number(value.replace(/\D/g, '')) || 0
  const percentageValid = discountKind !== 'percentage' || (parsedValue > 0 && parsedValue <= 100)
  const complete = slug.trim().length >= 2 && nameFa.trim() !== '' && parsedValue > 0 && percentageValid

  const submit = async () => {
    setBusy(true)
    setFailure(null)
    try {
      await api.saveCampaign({
        slug: slug.trim(),
        kind,
        nameFa: nameFa.trim(),
        discountKind,
        // Basis points for a percentage, Toman for a fixed amount.
        discountValue: discountKind === 'percentage' ? basisPoints(parsedValue) : parsedValue,
      })
      onCreated()
      onClose()
      setSlug('')
      setNameFa('')
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{'کمپین جدید'}</DialogTitle>
          <DialogDescription>
            {'کمپین متوقف ساخته می‌شود. بعد از بررسی، از همین جدول فعالش کنید.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          <Field label={'نام کمپین'}>
            <Input value={nameFa} onChange={(event) => setNameFa(event.target.value)} autoFocus />
          </Field>

          <Field label={'شناسه'} hint={'حروف کوچک انگلیسی، حداقل ۲ نویسه'}>
            <Input
              ltr
              value={slug}
              onChange={(event) => setSlug(event.target.value.toLowerCase())}
              placeholder="nowruz-1405"
            />
          </Field>

          <Field label={'نوع کمپین'}>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="seasonal">{'مناسبتی'}</SelectItem>
                <SelectItem value="flash_sale">{'فروش لحظه‌ای'}</SelectItem>
                <SelectItem value="launch">{'معرفی محصول'}</SelectItem>
                <SelectItem value="winback">{'بازگرداندن مشتری'}</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label={'نوع تخفیف'}>
              <Select
                value={discountKind}
                onValueChange={(next) => setDiscountKind(next as 'percentage' | 'fixed_amount')}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="percentage">{'درصدی'}</SelectItem>
                  <SelectItem value="fixed_amount">{'مبلغ ثابت'}</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field
              label={discountKind === 'percentage' ? 'درصد تخفیف' : 'مبلغ تخفیف (تومان)'}
              error={!percentageValid ? 'درصد باید بین ۱ تا ۱۰۰ باشد' : null}
            >
              <Input
                ltr
                inputMode="numeric"
                value={value}
                onChange={(event) => setValue(event.target.value)}
              />
            </Field>
          </div>

          {failure ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
              {failure}
            </p>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {'انصراف'}
          </Button>
          <Button loading={busy} disabled={!complete} onClick={submit}>
            {'ساخت کمپین'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
