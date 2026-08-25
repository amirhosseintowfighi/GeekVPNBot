'use client'

import * as React from 'react'
import { useParams } from 'next/navigation'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber, normalizeInput } from '@/lib/fa'
import { SUBSCRIPTION_STATE } from '@/lib/labels'
import type { AdminSubscriptionRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
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
import { Field, Input, Textarea } from '@/components/ui/input'
import { SkeletonCards } from '@/components/ui/skeleton'

const MIB_PER_GIB = 1024

/**
 * One subscription, and everything an operator can do to it.
 *
 * This screen did not exist. The customer page linked to it, the API served
 * `GET /admin/subscriptions/{id}`, and the route was not in the navigation
 * table - so the guard, which denies anything it does not recognise, answered
 * "your role does not have access" to an owner holding every permission there
 * is. The message was true about the route and false about the person.
 *
 * Every action below reaches the VPN panel before it changes our record. A
 * failure therefore means nothing was promised: the panel refused, and the
 * subscription still says exactly what it said before.
 */
type Action = 'suspend' | 'revoke' | 'extend' | 'traffic' | null

export default function SubscriptionPage() {
  const params = useParams<{ subscriptionId: string }>()
  const { can } = useSession()
  const id = params.subscriptionId

  const [action, setAction] = React.useState<Action>(null)
  const [reason, setReason] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)
  const [notice, setNotice] = React.useState<string | null>(null)

  const { data, error, isLoading, mutate } = useSWR<AdminSubscriptionRow>(
    ['subscription', id],
    () => api.subscription(id),
  )

  if (!can('subscriptions.read')) return <ForbiddenState permission="subscriptions.read" />

  const close = () => {
    setAction(null)
    setReason('')
    setAmount('')
    setActionError(null)
  }

  const parsedAmount = Number(normalizeInput(amount).replace(/[^\d]/g, '')) || 0
  const reasonTooShort = reason.trim().length < 3

  async function run(work: () => Promise<unknown>, message: string) {
    setBusy(true)
    setActionError(null)
    try {
      await work()
      setNotice(message)
      await mutate()
      close()
    } catch (thrown) {
      setActionError(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  const submit = () => {
    if (action === 'suspend') {
      return run(() => api.suspendSubscription(id, reason.trim()), 'اشتراک تعلیق شد.')
    }
    if (action === 'revoke') {
      return run(() => api.revokeSubscription(id, reason.trim()), 'اشتراک لغو شد.')
    }
    if (action === 'extend') {
      return run(() => api.extendSubscription(id, parsedAmount), 'مدت اشتراک تمدید شد.')
    }
    if (action === 'traffic') {
      return run(() => api.addSubscriptionTraffic(id, parsedAmount), 'حجم اضافه شد.')
    }
    return undefined
  }

  if (error) {
    return (
      <ErrorState
        messageFa={error instanceof ApiError ? error.messageFa : ''}
        offline={error instanceof ApiError && error.status === 0}
        onRetry={() => mutate()}
      />
    )
  }

  if (isLoading || !data) return <SkeletonCards count={2} />

  const meta = SUBSCRIPTION_STATE[data.state]
  const revoked = data.state === 'revoked'
  const suspended = data.state === 'suspended'
  const canWrite = can('subscriptions.write')

  const usedGib = data.trafficUsedMib / MIB_PER_GIB
  const limitGib = data.trafficLimitMib === null ? null : data.trafficLimitMib / MIB_PER_GIB

  return (
    <>
      <PageHeader
        breadcrumb={{ href: '/users', labelFa: 'کاربران' }}
        title={'اشتراک'}
        description={data.remoteUsername ?? data.id}
        actions={
          canWrite ? (
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                loading={busy}
                onClick={() =>
                  void run(() => api.syncSubscriptionUsage(id), 'مصرف از پنل خوانده شد.')
                }
              >
                {'به‌روزرسانی مصرف'}
              </Button>
              {/* Revoked is final: the panel account is gone, and every button
                  below would ask it to change something that no longer exists. */}
              {revoked ? null : (
                <>
                  <Button size="sm" variant="outline" onClick={() => setAction('extend')}>
                    {'تمدید'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setAction('traffic')}>
                    {'افزودن حجم'}
                  </Button>
                  {suspended ? (
                    <Button
                      size="sm"
                      variant="outline"
                      loading={busy}
                      onClick={() =>
                        void run(() => api.resumeSubscription(id), 'اشتراک دوباره فعال شد.')
                      }
                    >
                      {'رفع تعلیق'}
                    </Button>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => setAction('suspend')}>
                      {'تعلیق'}
                    </Button>
                  )}
                  <Button size="sm" variant="destructive" onClick={() => setAction('revoke')}>
                    {'لغو اشتراک'}
                  </Button>
                </>
              )}
            </div>
          ) : null
        }
      />

      {notice ? (
        <p className="rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-2xs text-success">
          {notice}
        </p>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{'وضعیت'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row labelFa={'وضعیت'}>
              <Badge variant={meta.tone} dot>
                {meta.fa}
              </Badge>
            </Row>
            <Row labelFa={'شروع'}>{faDateTime(data.startedAt)}</Row>
            <Row labelFa={'انقضا'}>{faDateTime(data.expiresAt)}</Row>
            <Row labelFa={'تعداد دستگاه'}>{faNumber(data.deviceLimit)}</Row>
            {data.revokedAt ? <Row labelFa={'لغو شده در'}>{faDateTime(data.revokedAt)}</Row> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{'مصرف و اتصال'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row labelFa={'مصرف'}>
              {limitGib === null
                ? faNumber(Math.round(usedGib)) + ' گیگابایت (نامحدود)'
                : faNumber(Math.round(usedGib)) + ' از ' + faNumber(Math.round(limitGib)) + ' گیگابایت'}
            </Row>
            <Row labelFa={'آخرین همگام‌سازی'}>
              {data.lastSyncedAt ? faDateTime(data.lastSyncedAt) : '—'}
            </Row>
            <Row labelFa={'سرور'}>
              <span dir="ltr" className="font-mono">
                {data.nodeId ?? '—'}
              </span>
            </Row>
            <Row labelFa={'نام کاربری پنل'}>
              <span dir="ltr" className="font-mono">
                {data.remoteUsername ?? '—'}
              </span>
            </Row>
            {data.subscriptionUrl ? (
              <Row labelFa={'لینک اشتراک'}>
                <span dir="ltr" className="max-w-[16rem] truncate font-mono">
                  {data.subscriptionUrl}
                </span>
              </Row>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Dialog open={action !== null} onOpenChange={(open) => (open ? null : close())}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {action === 'suspend'
                ? 'تعلیق اشتراک'
                : action === 'revoke'
                  ? 'لغو اشتراک'
                  : action === 'extend'
                    ? 'تمدید اشتراک'
                    : 'افزودن حجم'}
            </DialogTitle>
            <DialogDescription>
              {action === 'suspend'
                ? 'اتصال قطع می‌شود ولی اکانت روی پنل می‌ماند و بعداً قابل بازگرداندن است.'
                : action === 'revoke'
                  ? 'اکانت از روی پنل حذف می‌شود. این کار برگشت‌پذیر نیست.'
                  : action === 'extend'
                    ? 'روزهای اضافه بدون دریافت وجه به اشتراک اضافه می‌شود.'
                    : 'حجم اضافه بدون دریافت وجه به سقف اشتراک اضافه می‌شود.'}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-3">
            {action === 'extend' || action === 'traffic' ? (
              <Field label={action === 'extend' ? 'تعداد روز' : 'حجم (گیگابایت)'}>
                <Input
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  dir="ltr"
                  inputMode="numeric"
                  placeholder={action === 'extend' ? '30' : '20'}
                />
              </Field>
            ) : (
              <Field label={'دلیل'}>
                <Textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  rows={3}
                />
              </Field>
            )}

            {actionError ? <p className="text-2xs text-destructive">{actionError}</p> : null}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={close} disabled={busy}>
              {'انصراف'}
            </Button>
            <Button
              size="sm"
              variant={action === 'revoke' ? 'destructive' : 'default'}
              loading={busy}
              onClick={() => void submit()}
              disabled={
                busy ||
                ((action === 'extend' || action === 'traffic') && parsedAmount <= 0) ||
                ((action === 'suspend' || action === 'revoke') && reasonTooShort)
              }
            >
              {'تأیید'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Row({ labelFa, children }: { labelFa: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{labelFa}</span>
      <span className="nums">{children}</span>
    </div>
  )
}
