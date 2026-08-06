'use client'

import * as React from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDate, faDateTime, faNumber, gib, normalizeInput, toman } from '@/lib/fa'
import { SUBSCRIPTION_STATE, USER_STATE } from '@/lib/labels'
import type { UserDetail, UserState } from '@/lib/types'
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Progress, usageTone } from '@/components/ui/primitives'

type DialogKind = 'state' | 'wallet' | null

/**
 * User detail.
 *
 * Both mutating actions here are ones a customer feels immediately, so both
 * demand a written reason:
 *
 * - Changing state to suspended or banned cuts off a paying customer. The
 *   reason is stored on the audit trail and is what support quotes back when
 *   the customer asks why.
 * - A wallet adjustment is money created or destroyed by hand. It is the most
 *   abusable action in the panel, so the reason is mandatory, the amount is
 *   signed, and the resulting balance is previewed before confirming.
 */
export default function UserDetailPage() {
  const params = useParams<{ userId: string }>()
  const { can } = useSession()
  const userId = params.userId

  const [dialog, setDialog] = React.useState<DialogKind>(null)
  const [nextState, setNextState] = React.useState<UserState>('suspended')
  const [reason, setReason] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)

  const { data, error, isLoading, mutate } = useSWR<UserDetail>(['user', userId], () => api.user(userId))

  if (!can('users.view')) return <ForbiddenState permission="users.view" />

  const close = () => {
    setDialog(null)
    setReason('')
    setAmount('')
    setActionError(null)
  }

  // Persian digits in, integer tomans out. An empty or malformed amount is 0,
  // which the confirm button treats as invalid rather than silently posting.
  const parsedAmount = Number(normalizeInput(amount).replace(/[^\d-]/g, '')) || 0
  const reasonTooShort = reason.trim().length < 5

  const submit = async () => {
    if (!data) return
    setBusy(true)
    setActionError(null)
    try {
      if (dialog === 'state') await api.setUserState(userId, nextState, reason.trim())
      if (dialog === 'wallet') await api.adjustWallet(userId, parsedAmount, reason.trim())
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

  const stateMeta = USER_STATE[data.state]

  return (
    <>
      <PageHeader
        breadcrumb={[{ href: '/users', labelFa: '\u06a9\u0627\u0631\u0628\u0631\u0627\u0646' }]}
        title={data.displayNameFa}
        description={
          '\u0639\u0636\u0648 \u0627\u0632 ' + faDate(data.createdAt)
        }
        actions={
          <div className="flex flex-wrap gap-2">
            {can('wallet.adjust') ? (
              <Button variant="outline" onClick={() => setDialog('wallet')}>
                {'\u062a\u0639\u062f\u06cc\u0644 \u06a9\u06cc\u0641 \u067e\u0648\u0644'}
              </Button>
            ) : null}

            {can('users.suspend') ? (
              <Button
                variant={data.state === 'active' ? 'destructive' : 'success'}
                onClick={() => {
                  setNextState(data.state === 'active' ? 'suspended' : 'active')
                  setDialog('state')
                }}
              >
                {data.state === 'active'
                  ? '\u062a\u0639\u0644\u06cc\u0642 \u06a9\u0627\u0631\u0628\u0631'
                  : '\u0631\u0641\u0639 \u0645\u062d\u062f\u0648\u062f\u06cc\u062a'}
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-3 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{'\u067e\u0631\u0648\u0641\u0627\u06cc\u0644'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-2xs">
            <Row label={'\u0648\u0636\u0639\u06cc\u062a'}>
              <Badge variant={stateMeta.tone} dot>
                {stateMeta.fa}
              </Badge>
            </Row>
            <Row label={'\u0634\u0646\u0627\u0633\u0647\u0654 \u062a\u0644\u06af\u0631\u0627\u0645'}>
              <span dir="ltr" className="font-mono">{data.telegramId}</span>
            </Row>
            <Row label={'\u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc'}>
              <span dir="ltr" className="font-mono">{data.username ? '@' + data.username : '\u2014'}</span>
            </Row>
            <Row label={'\u0633\u0637\u062d \u0648\u0641\u0627\u062f\u0627\u0631\u06cc'}>
              <span>
                {data.tierEmoji} {data.tierLabelFa}
              </span>
            </Row>
            <Row label={'\u0645\u062c\u0645\u0648\u0639 \u062e\u0631\u06cc\u062f'}>
              <span className="nums">{toman(data.lifetimeSpend)}</span>
            </Row>
            <Row label={'\u0645\u0648\u062c\u0648\u062f\u06cc \u06a9\u06cc\u0641 \u067e\u0648\u0644'}>
              <span className="nums font-semibold">{toman(data.walletBalance)}</span>
            </Row>
            <Row label={'\u0645\u0639\u0631\u0641\u06cc\u200c\u0634\u062f\u06af\u0627\u0646'}>
              <span className="nums">{faNumber(data.referralCount)}</span>
            </Row>
            {data.referredByFa ? (
              <Row label={'\u0645\u0639\u0631\u0641'}>
                <span>{data.referredByFa}</span>
              </Row>
            ) : null}
            {data.stateReasonFa ? (
              <p className="rounded-md border border-warning/30 bg-warning/10 px-2.5 py-2 text-warning">
                {data.stateReasonFa}
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{'\u0627\u0634\u062a\u0631\u0627\u06a9\u200c\u0647\u0627'}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {data.subscriptions.length === 0 ? (
              <p className="px-4 py-6 text-center text-2xs text-muted-foreground">
                {'\u0627\u06cc\u0646 \u06a9\u0627\u0631\u0628\u0631 \u0647\u0646\u0648\u0632 \u0627\u0634\u062a\u0631\u0627\u06a9\u06cc \u0646\u062f\u0627\u0631\u062f.'}
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{'\u067e\u0644\u0646'}</TableHead>
                    <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                    <TableHead>{'\u0645\u0635\u0631\u0641'}</TableHead>
                    <TableHead>{'\u0627\u0646\u0642\u0636\u0627'}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.subscriptions.map((subscription) => {
                    const meta = SUBSCRIPTION_STATE[subscription.state]
                    // Unlimited plans have no quota; a progress bar there would
                    // imply a ceiling that does not exist.
                    const unlimited = subscription.quotaGib === null
                    const fraction = unlimited
                      ? 0
                      : Math.min(1, subscription.usedGib / Math.max(1, subscription.quotaGib ?? 1))

                    return (
                      <TableRow key={subscription.id}>
                        <TableCell>{subscription.planNameFa}</TableCell>
                        <TableCell>
                          <Badge variant={meta.tone} dot>
                            {meta.fa}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {unlimited ? (
                            <span className="text-muted-foreground">{gib(null)}</span>
                          ) : (
                            <div className="min-w-28 space-y-1">
                              <Progress value={fraction * 100} tone={usageTone(fraction)} />
                              <span className="nums text-2xs text-muted-foreground">
                                {gib(subscription.usedGib) + ' / ' + gib(subscription.quotaGib)}
                              </span>
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {subscription.expiresAt ? faDate(subscription.expiresAt) : '\u2014'}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{'\u0622\u062e\u0631\u06cc\u0646 \u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627'}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc'}</TableHead>
                <TableHead>{'\u0645\u0628\u0644\u063a'}</TableHead>
                <TableHead>{'\u062a\u0627\u0631\u06cc\u062e'}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recentOrders.map((order) => (
                <TableRow key={order.id}>
                  <TableCell>
                    <Link
                      href={'/orders/' + order.id}
                      dir="ltr"
                      className="font-mono text-2xs text-primary hover:underline"
                    >
                      {order.reference}
                    </Link>
                  </TableCell>
                  <TableCell numeric>{toman(order.amount, false)}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {faDateTime(order.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={dialog !== null} onOpenChange={(open) => (open ? null : close())}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog === 'wallet'
                ? '\u062a\u0639\u062f\u06cc\u0644 \u062f\u0633\u062a\u06cc \u06a9\u06cc\u0641 \u067e\u0648\u0644'
                : '\u062a\u063a\u06cc\u06cc\u0631 \u0648\u0636\u0639\u06cc\u062a \u06a9\u0627\u0631\u0628\u0631'}
            </DialogTitle>
            <DialogDescription>
              {dialog === 'wallet'
                ? '\u0645\u0628\u0644\u063a \u0645\u062b\u0628\u062a \u0628\u0631\u0627\u06cc \u0648\u0627\u0631\u06cc\u0632 \u0648 \u0645\u0646\u0641\u06cc \u0628\u0631\u0627\u06cc \u0628\u0631\u062f\u0627\u0634\u062a. \u0627\u06cc\u0646 \u062a\u0631\u0627\u06a9\u0646\u0634 \u062f\u0631 \u0644\u0627\u06af \u062b\u0628\u062a \u0645\u06cc\u200c\u0634\u0648\u062f.'
                : '\u062f\u0644\u06cc\u0644 \u0628\u0631\u0627\u06cc \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0642\u0627\u0628\u0644 \u0645\u0634\u0627\u0647\u062f\u0647 \u062e\u0648\u0627\u0647\u062f \u0628\u0648\u062f.'}
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="space-y-3">
            {dialog === 'wallet' ? (
              <>
                <Field label={'\u0645\u0628\u0644\u063a (\u062a\u0648\u0645\u0627\u0646)'}>
                  <Input
                    ltr
                    inputMode="numeric"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    autoFocus
                  />
                </Field>

                {/* Preview the resulting balance. Signed adjustments are easy
                    to get backwards, and this is the last chance to notice. */}
                <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-2xs">
                  <span className="text-muted-foreground">
                    {'\u0645\u0648\u062c\u0648\u062f\u06cc \u067e\u0633 \u0627\u0632 \u062a\u0639\u062f\u06cc\u0644'}
                  </span>
                  <span className="nums font-semibold">{toman(data.walletBalance + parsedAmount)}</span>
                </div>
              </>
            ) : null}

            <Field
              label={'\u0639\u0644\u062a'}
              hint={'\u062f\u0633\u062a\u200c\u06a9\u0645 \u06f5 \u062d\u0631\u0641'}
              error={reason.length > 0 && reasonTooShort ? '\u0639\u0644\u062a \u062e\u06cc\u0644\u06cc \u06a9\u0648\u062a\u0627\u0647 \u0627\u0633\u062a' : undefined}
            >
              <Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} />
            </Field>

            {actionError ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
                {actionError}
              </p>
            ) : null}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={close} disabled={busy}>
              {'\u0627\u0646\u0635\u0631\u0627\u0641'}
            </Button>
            <Button
              variant="destructive"
              loading={busy}
              disabled={reasonTooShort || (dialog === 'wallet' && parsedAmount === 0)}
              onClick={submit}
            >
              {'\u062a\u0623\u06cc\u06cc\u062f'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}
