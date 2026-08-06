'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Send, Users } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime, faNumber } from '@/lib/fa'
import { BROADCAST_STATE } from '@/lib/labels'
import type { BroadcastAudience, BroadcastRow } from '@/lib/types'
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
import { Field, Textarea } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Progress } from '@/components/ui/primitives'

/** Segments mirror the read models the bot already exposes; no new query
 *  language, so an operator cannot express an audience the backend cannot
 *  actually resolve. */
const SEGMENTS: Array<{ value: BroadcastAudience['segment']; labelFa: string }> = [
  { value: 'all', labelFa: '\u0647\u0645\u0647\u0654 \u06a9\u0627\u0631\u0628\u0631\u0627\u0646' },
  { value: 'active', labelFa: '\u062f\u0627\u0631\u0627\u06cc \u0627\u0634\u062a\u0631\u0627\u06a9 \u0641\u0639\u0627\u0644' },
  { value: 'expiring', labelFa: '\u0631\u0648 \u0628\u0647 \u0627\u062a\u0645\u0627\u0645' },
  { value: 'expired', labelFa: '\u0645\u0646\u0642\u0636\u06cc\u200c\u0634\u062f\u0647' },
  { value: 'never_purchased', labelFa: '\u0628\u062f\u0648\u0646 \u062e\u0631\u06cc\u062f' },
]

/**
 * Broadcast.
 *
 * The most dangerous button in the panel: it writes into tens of thousands of
 * private chats and cannot be recalled. Four guards, all deliberate:
 *
 * 1. The audience is estimated from the server before sending, and the
 *    confirm dialog restates that count. "Send to everyone" must be a number
 *    the operator has actually read.
 * 2. Sending is gated on `broadcast.send`, a separate permission from
 *    `broadcast.view`, so drafting and firing are different privileges.
 * 3. The message is categorised, and the category drives both the customer's
 *    notification preferences and quiet hours. Promotional traffic honours
 *    the 23:00-08:00 window; only CRITICAL bypasses it. An operator can see
 *    this before sending rather than discovering it in complaints.
 * 4. A send in progress shows real delivery counts, because Telegram rate
 *    limits mean a large broadcast takes minutes, and an operator who thinks
 *    it failed will otherwise send it twice.
 */
export default function BroadcastPage() {
  const { can } = useSession()
  const [composeOpen, setComposeOpen] = React.useState(false)

  const { data, error, isLoading, mutate } = useSWR<BroadcastRow[]>('broadcasts', () => api.broadcasts())

  if (!can('broadcast.view')) return <ForbiddenState permission="broadcast.view" />

  return (
    <>
      <PageHeader
        title={'\u067e\u06cc\u0627\u0645 \u0647\u0645\u06af\u0627\u0646\u06cc'}
        description={'\u0627\u0631\u0633\u0627\u0644 \u067e\u06cc\u0627\u0645 \u0628\u0647 \u0628\u062e\u0634\u200c\u0647\u0627\u06cc \u0645\u0634\u062e\u0635\u06cc \u0627\u0632 \u06a9\u0627\u0631\u0628\u0631\u0627\u0646'}
        actions={
          can('broadcast.send') ? (
            <Button onClick={() => setComposeOpen(true)}>
              <Send className="size-3.5" aria-hidden />
              {'\u067e\u06cc\u0627\u0645 \u062c\u062f\u06cc\u062f'}
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
        <CardHeader>
          <CardTitle>{'\u062a\u0627\u0631\u06cc\u062e\u0686\u0647\u0654 \u0627\u0631\u0633\u0627\u0644'}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && !data ? (
            <SkeletonTable rows={6} cols={5} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'\u0645\u062a\u0646'}</TableHead>
                  <TableHead>{'\u0645\u062e\u0627\u0637\u0628'}</TableHead>
                  <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                  <TableHead>{'\u062a\u062d\u0648\u06cc\u0644'}</TableHead>
                  <TableHead>{'\u0632\u0645\u0627\u0646'}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data ?? []).map((broadcast) => {
                  const meta = BROADCAST_STATE[broadcast.state]
                  const sending = broadcast.state === 'sending'
                  const progress =
                    broadcast.audienceSize > 0
                      ? (broadcast.deliveredCount / broadcast.audienceSize) * 100
                      : 0

                  return (
                    <TableRow key={broadcast.id}>
                      <TableCell className="max-w-72 truncate">{broadcast.bodyFa}</TableCell>
                      <TableCell className="text-muted-foreground">{broadcast.segmentLabelFa}</TableCell>
                      <TableCell>
                        <Badge variant={meta.tone} dot>
                          {meta.fa}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="min-w-28 space-y-1">
                          <Progress value={progress} />
                          <span className="nums text-2xs text-muted-foreground">
                            {faNumber(broadcast.deliveredCount) + ' / ' + faNumber(broadcast.audienceSize)}
                            {broadcast.failedCount > 0
                              ? ' \u00b7 ' + faNumber(broadcast.failedCount) + ' \u0646\u0627\u0645\u0648\u0641\u0642'
                              : ''}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {faDateTime(broadcast.createdAt)}
                      </TableCell>
                      <TableCell>
                        {/* Cancel only exists while a send is in flight: it
                            stops the remaining chunks, it does not unsend. */}
                        {sending && can('broadcast.send') ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={async () => {
                              await api.cancelBroadcast(broadcast.id)
                              mutate()
                            }}
                          >
                            {'\u062a\u0648\u0642\u0641'}
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ComposeDialog open={composeOpen} onClose={() => setComposeOpen(false)} onSent={() => mutate()} />
    </>
  )
}

function ComposeDialog({
  open,
  onClose,
  onSent,
}: {
  open: boolean
  onClose: () => void
  onSent: () => void
}) {
  const [segment, setSegment] = React.useState<BroadcastAudience['segment']>('active')
  const [body, setBody] = React.useState('')
  const [category, setCategory] = React.useState<'promos' | 'news' | 'critical'>('news')
  const [respectQuiet, setRespectQuiet] = React.useState(true)
  const [confirming, setConfirming] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  const estimate = useSWR<{ count: number }>(
    open ? ['audience', segment] : null,
    () => api.estimateAudience({ segment }),
  )

  const bodyValid = body.trim().length >= 10
  // CRITICAL is the only category allowed to wake people up, and the switch
  // is disabled rather than hidden so the rule is visible.
  const canBypassQuiet = category === 'critical'

  const send = async () => {
    setBusy(true)
    setFailure(null)
    try {
      await api.sendBroadcast({
        segment,
        bodyFa: body.trim(),
        category,
        respectQuietHours: canBypassQuiet ? respectQuiet : true,
      })
      onSent()
      setBody('')
      setConfirming(false)
      onClose()
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setConfirming(false)
          onClose()
        }
      }}
    >
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{'\u067e\u06cc\u0627\u0645 \u0647\u0645\u06af\u0627\u0646\u06cc \u062c\u062f\u06cc\u062f'}</DialogTitle>
          <DialogDescription>
            {'\u0627\u06cc\u0646 \u067e\u06cc\u0627\u0645 \u062f\u0631 \u06af\u0641\u062a\u06af\u0648\u06cc \u062e\u0635\u0648\u0635\u06cc \u06a9\u0627\u0631\u0628\u0631\u0627\u0646 \u0627\u0631\u0633\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f \u0648 \u0642\u0627\u0628\u0644 \u0628\u0627\u0632\u06af\u0634\u062a \u0646\u06cc\u0633\u062a.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          <Field label={'\u0645\u062e\u0627\u0637\u0628'}>
            <Select value={segment} onValueChange={(value) => setSegment(value as BroadcastAudience['segment'])}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SEGMENTS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.labelFa}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <div className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-2 text-2xs">
            <Users className="size-3.5 text-muted-foreground" aria-hidden />
            <span className="text-muted-foreground">{'\u0628\u0631\u0622\u0648\u0631\u062f \u0645\u062e\u0627\u0637\u0628\u0627\u0646:'}</span>
            <span className="nums font-semibold">
              {estimate.isLoading
                ? '\u2026'
                : faNumber(estimate.data?.count ?? 0) + ' \u06a9\u0627\u0631\u0628\u0631'}
            </span>
          </div>

          <Field label={'\u062f\u0633\u062a\u0647\u200c\u0628\u0646\u062f\u06cc'}>
            <Select value={category} onValueChange={(value) => setCategory(value as typeof category)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="promos">{'\u062a\u0628\u0644\u06cc\u063a\u0627\u062a \u0648 \u062a\u062e\u0641\u06cc\u0641'}</SelectItem>
                <SelectItem value="news">{'\u0627\u062e\u0628\u0627\u0631 \u0633\u0631\u0648\u06cc\u0633'}</SelectItem>
                <SelectItem value="critical">{'\u0627\u0637\u0644\u0627\u0639\u06cc\u0647\u0654 \u0628\u062d\u0631\u0627\u0646\u06cc'}</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <div className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
            <div>
              <p className="text-2xs font-medium">{'\u0631\u0639\u0627\u06cc\u062a \u0633\u0627\u0639\u0627\u062a \u0633\u06a9\u0648\u062a'}</p>
              <p className="text-2xs text-muted-foreground">
                {'\u06f2\u06f3 \u062a\u0627 \u06f8 \u0628\u0647 \u0648\u0642\u062a \u062a\u0647\u0631\u0627\u0646. \u0641\u0642\u0637 \u0627\u0637\u0644\u0627\u0639\u06cc\u0647\u0654 \u0628\u062d\u0631\u0627\u0646\u06cc \u0645\u06cc\u200c\u062a\u0648\u0627\u0646\u062f \u0627\u0632 \u0622\u0646 \u0639\u0628\u0648\u0631 \u06a9\u0646\u062f.'}
              </p>
            </div>
            <Switch
              checked={canBypassQuiet ? respectQuiet : true}
              disabled={!canBypassQuiet}
              onCheckedChange={setRespectQuiet}
            />
          </div>

          <Field
            label={'\u0645\u062a\u0646 \u067e\u06cc\u0627\u0645'}
            hint={'\u062f\u0633\u062a\u200c\u06a9\u0645 \u06f1\u06f0 \u062d\u0631\u0641'}
          >
            <Textarea value={body} onChange={(event) => setBody(event.target.value)} rows={5} />
          </Field>

          {confirming ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
              {'\u0627\u06cc\u0646 \u067e\u06cc\u0627\u0645 \u0628\u0631\u0627\u06cc ' +
                faNumber(estimate.data?.count ?? 0) +
                ' \u06a9\u0627\u0631\u0628\u0631 \u0627\u0631\u0633\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f. \u0645\u0637\u0645\u0626\u0646\u06cc\u062f\u061f'}
            </p>
          ) : null}

          {failure ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
              {failure}
            </p>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              setConfirming(false)
              onClose()
            }}
            disabled={busy}
          >
            {'\u0627\u0646\u0635\u0631\u0627\u0641'}
          </Button>

          {/* Two-step: the first click only reveals the count. */}
          {confirming ? (
            <Button variant="destructive" loading={busy} onClick={send}>
              {'\u0627\u0631\u0633\u0627\u0644 \u0646\u0647\u0627\u06cc\u06cc'}
            </Button>
          ) : (
            <Button disabled={!bodyValid} onClick={() => setConfirming(true)}>
              {'\u0628\u0631\u0631\u0633\u06cc \u0648 \u0627\u0631\u0633\u0627\u0644'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
