'use client'

import * as React from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDate, faDateTime, faNumber, gib, normalizeInput, toman } from '@/lib/fa'
import { SUBSCRIPTION_STATE, USER_STATE } from '@/lib/labels'
import type { AdminSubscriptionRow, Paged, UserDetail } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
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
import { Field, Input, Textarea } from '@/components/ui/input'
import { SkeletonCards } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type DialogKind = 'state' | 'wallet' | 'message' | null

/**
 * One customer.
 *
 * Assembled from three endpoints, because that is how the API is shaped:
 * `/customers/{id}` returns the customer plus two counts - not, as this screen
 * assumed, a nested list of subscriptions and orders and a wallet balance.
 * The balance comes from `/wallet/{id}` and the subscriptions from
 * `/subscriptions?user_id=`, which is also what makes them paginated and
 * filterable instead of silently capped at whatever the detail call chose.
 */
// Subscriptions store MiB; every screen reads gigabytes.
const MIB_PER_GIB = 1024

export default function UserDetailPage() {
  const params = useParams<{ userId: string }>()
  const { can } = useSession()
  const userId = params.userId

  const [dialog, setDialog] = React.useState<DialogKind>(null)
  const [reason, setReason] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [title, setTitle] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)

  const { data, error, isLoading, mutate } = useSWR<UserDetail>(
    ['user', userId],
    () => api.user(userId),
  )

  // Keyed by Telegram id, which only arrives with `data`. Passing the
  // route's UUID here asked for a wallet belonging to nobody: the balance
  // never rendered and every adjustment was rejected before reaching the
  // ledger.
  const telegramId = data?.customer.telegramId
  const { data: wallet, mutate: mutateWallet } = useSWR(
    telegramId !== undefined && can('wallet.read') ? ['wallet', telegramId] : null,
    () => api.walletBalance(String(telegramId)),
  )

  const { data: subscriptions } = useSWR<Paged<AdminSubscriptionRow>>(
    data ? ['user-subscriptions', userId] : null,
    () => api.subscriptions({ page: 1, userId: data ? data.customer.telegramId : undefined }),
  )

  if (!can('users.read')) return <ForbiddenState permission="users.read" />

  const close = () => {
    setDialog(null)
    setReason('')
    setAmount('')
    setTitle('')
    setActionError(null)
  }

  // Persian digits in, integer tomans out. A signed amount: negative debits.
  const parsedAmount = Number(normalizeInput(amount).replace(/[^\d-]/g, '')) || 0
  const reasonTooShort = reason.trim().length < 5

  const submit = async () => {
    if (!data) return
    setBusy(true)
    setActionError(null)
    try {
      if (dialog === 'state') {
        await (data.customer.status === 'active'
          ? api.suspendUser(userId, reason.trim())
          : api.reinstateUser(userId))
      }
      if (dialog === 'wallet' && telegramId !== undefined) {
        await api.adjustWallet(String(telegramId), parsedAmount, reason.trim())
        await mutateWallet()
      }
      if (dialog === 'message') {
        await api.messageCustomer(userId, title.trim(), reason.trim())
      }
      await mutate()
      close()
    } catch (thrown) {
      setActionError(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
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

  if (isLoading || !data) return <SkeletonCards count={3} />

  const customer = data.customer
  const stateMeta = USER_STATE[customer.status]
  const suspended = customer.status !== 'active'

  return (
    <>
      <PageHeader
        breadcrumb={{ href: '/users', labelFa: 'کاربران' }}
        title={customer.displayName}
        description={'عضویت ' + faDate(customer.createdAt)}
        actions={
          <div className="flex flex-wrap gap-2">
            {can('users.suspend') ? (
              <Button
                size="sm"
                variant={suspended ? 'outline' : 'destructive'}
                onClick={() => setDialog('state')}
              >
                {suspended ? 'رفع مسدودی' : 'مسدودسازی'}
              </Button>
            ) : null}
            {can('wallet.adjust') ? (
              <Button size="sm" variant="outline" onClick={() => setDialog('wallet')}>
                {'اصلاح کیف پول'}
              </Button>
            ) : null}
            {can('broadcast.send') ? (
              <Button size="sm" onClick={() => setDialog('message')}>
                {'ارسال پیام'}
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-3 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{'هویت'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row labelFa={'وضعیت'}>
              <Badge variant={stateMeta.tone} dot>
                {stateMeta.fa}
              </Badge>
            </Row>
            <Row labelFa={'شناسهٔ تلگرام'}>
              <span dir="ltr" className="font-mono">
                {customer.telegramId}
              </span>
            </Row>
            <Row labelFa={'نام کاربری'}>
              <span dir="ltr" className="font-mono">
                {customer.username ? '@' + customer.username : '—'}
              </span>
            </Row>
            <Row labelFa={'کد معرف'}>
              <span dir="ltr" className="font-mono">
                {customer.referralCode}
              </span>
            </Row>
            <Row labelFa={'معرفی‌شده توسط'}>
              <span dir="ltr" className="font-mono">
                {customer.referredByCode ?? '—'}
              </span>
            </Row>
            <Row labelFa={'آخرین بازدید'}>
              {customer.lastSeenAt ? faDateTime(customer.lastSeenAt) : '—'}
            </Row>
            {customer.suspendedReason ? (
              <Row labelFa={'علت مسدودی'}>
                <span className="text-destructive">{customer.suspendedReason}</span>
              </Row>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{'خلاصه'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row labelFa={'اشتراک‌ها'}>{faNumber(data.subscriptions)}</Row>
            <Row labelFa={'سفارش‌ها'}>{faNumber(data.orders)}</Row>
            <Row labelFa={'موجودی کیف پول'}>
              {wallet ? toman(wallet.balance, false) : '—'}
            </Row>
            <Row labelFa={'مشتری ویژه'}>{customer.isPremium ? 'بله' : 'خیر'}</Row>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{'اشتراک‌ها'}</CardTitle>
        </CardHeader>
        {!subscriptions || subscriptions.items.length === 0 ? (
          <EmptyState title={'اشتراکی ندارد'} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'اشتراک'}</TableHead>
                <TableHead>{'وضعیت'}</TableHead>
                <TableHead>{'شروع'}</TableHead>
                <TableHead>{'انقضا'}</TableHead>
                <TableHead numeric>{'مصرف'}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {subscriptions.items.map((subscription) => {
                const meta = SUBSCRIPTION_STATE[subscription.state]
                return (
                  <TableRow key={subscription.id}>
                    <TableCell>
                      <Link
                        href={'/subscriptions/' + subscription.id}
                        className="text-primary hover:underline"
                      >
                        {/* The panel username, not the plan id. A raw UUID
                            told nobody anything, and because the link beside
                            it points at the *subscription* while the text was
                            the *plan*, copying what you see and looking it up
                            finds nothing - which is exactly what happened. */}
                        {subscription.remoteUsername ?? subscription.id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant={meta.tone} dot>
                        {meta.fa}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {faDate(subscription.startedAt)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {faDate(subscription.expiresAt)}
                    </TableCell>
                    <TableCell numeric>
                      {/* `gib`, not a hand-rolled round: rounding to whole
                          gigabytes reported 3.44 GB as ۳ and everything
                          under half a gigabyte as ۰ - which reads exactly
                          like a usage figure that never updated. */}
                      {gib(subscription.trafficUsedMib / MIB_PER_GIB)}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <Dialog open={dialog !== null} onOpenChange={(open) => (open ? null : close())}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog === 'wallet'
                ? 'اصلاح کیف پول'
                : dialog === 'message'
                  ? 'ارسال پیام به کاربر'
                  : suspended
                    ? 'رفع مسدودی'
                    : 'مسدودسازی کاربر'}
            </DialogTitle>
            <DialogDescription>
              {dialog === 'wallet'
                ? 'مبلغ مثبت اعتبار می‌افزاید و مبلغ منفی کم می‌کند. هر دو در دفتر ثبت می‌شوند.'
                : dialog === 'message'
                  ? 'پیام مستقیم در تلگرام برای همین کاربر فرستاده می‌شود و در سوابق او ثبت می‌ماند.'
                  : suspended
                    ? 'کاربر دوباره می‌تواند خرید کند.'
                    : 'کاربر تا رفع مسدودی نمی‌تواند خرید کند.'}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-3">
            {dialog === 'wallet' ? (
              <Field label={'مبلغ (تومان)'}>
                <Input
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  dir="ltr"
                  inputMode="numeric"
                  placeholder="50000"
                />
              </Field>
            ) : null}

            {dialog === 'message' ? (
              <Field label={'عنوان'}>
                <Input value={title} onChange={(event) => setTitle(event.target.value)} />
              </Field>
            ) : null}

            {/* Reinstating needs no reason; every other action here does. The
                same textarea carries the message body - only one dialog is
                open at a time and `close` clears it. */}
            {dialog === 'wallet' || dialog === 'message' || !suspended ? (
              <Field label={dialog === 'message' ? 'متن پیام' : 'دلیل'}>
                <Textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  rows={3}
                />
              </Field>
            ) : null}

            {actionError ? <p className="text-2xs text-destructive">{actionError}</p> : null}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={close} disabled={busy}>
              {'انصراف'}
            </Button>
            <Button
              size="sm"
              onClick={submit}
              disabled={
                busy ||
                (dialog === 'wallet' && (parsedAmount === 0 || reasonTooShort)) ||
                (dialog === 'message' && (title.trim() === '' || reasonTooShort)) ||
                (dialog === 'state' && !suspended && reasonTooShort)
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
