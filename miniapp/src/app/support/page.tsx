'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { MessageSquarePlus, Plus } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { SkeletonList } from '@/components/ui/skeleton'
import { api, ApiError, fetcher } from '@/lib/api'
import { faNumber, faRelative, normalizeInput } from '@/lib/fa'
import { haptic } from '@/lib/telegram'
import type { TicketCard } from '@/lib/types'

/** Same floor the bot enforces, so a message accepted here is accepted there. */
const MIN_MESSAGE = 10

/** Topics mirror the bot's support handler exactly. */
const TOPICS = [
  { key: 'connection', labelFa: '\u0645\u0634\u06a9\u0644 \u0627\u062a\u0635\u0627\u0644' },
  { key: 'payment', labelFa: '\u067e\u0631\u062f\u0627\u062e\u062a \u0648 \u0645\u0627\u0644\u06cc' },
  { key: 'account', labelFa: '\u062d\u0633\u0627\u0628 \u06a9\u0627\u0631\u0628\u0631\u06cc' },
  { key: 'speed', labelFa: '\u0633\u0631\u0639\u062a \u0648 \u06a9\u06cc\u0641\u06cc\u062a' },
  { key: 'other', labelFa: '\u0633\u0627\u06cc\u0631 \u0645\u0648\u0627\u0631\u062f' },
] as const

const STATE_META: Record<
  TicketCard['state'],
  { labelFa: string; variant: 'warning' | 'success' | 'muted' }
> = {
  open: { labelFa: '\u0628\u0627\u0632', variant: 'warning' },
  answered: { labelFa: '\u067e\u0627\u0633\u062e \u062f\u0627\u062f\u0647 \u0634\u062f', variant: 'success' },
  closed: { labelFa: '\u0628\u0633\u062a\u0647 \u0634\u062f\u0647', variant: 'muted' },
}

export default function SupportPage() {
  const { data, error, mutate } = useSWR<TicketCard[]>(
    '/api/miniapp/tickets',
    fetcher,
  )

  const [open, setOpen] = React.useState(false)
  const [topic, setTopic] = React.useState<string>(TOPICS[0].key)
  const [subject, setSubject] = React.useState('')
  const [message, setMessage] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)

  const messageLength = normalizeInput(message).trim().length
  const valid = subject.trim().length > 0 && messageLength >= MIN_MESSAGE

  async function submit() {
    if (!valid) return
    setBusy(true)
    setFormError(null)
    try {
      await api.openTicket(topic, subject.trim(), normalizeInput(message).trim())
      haptic.notify('success')
      setOpen(false)
      setSubject('')
      setMessage('')
      void mutate()
    } catch (err) {
      haptic.notify('error')
      setFormError(
        err instanceof ApiError
          ? err.messageFa
          : '\u062b\u0628\u062a \u062a\u06cc\u06a9\u062a \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title={'\u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc'}
        action={
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button size="sm" onClick={haptic.select}>
                <Plus className="size-4" aria-hidden />
                {'\u062a\u06cc\u06a9\u062a \u062c\u062f\u06cc\u062f'}
              </Button>
            </SheetTrigger>

            <SheetContent>
              <SheetHeader>
                <SheetTitle>
                  {'\u062b\u0628\u062a \u062a\u06cc\u06a9\u062a \u062c\u062f\u06cc\u062f'}
                </SheetTitle>
              </SheetHeader>

              <div className="space-y-4">
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    {'\u0645\u0648\u0636\u0648\u0639'}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {TOPICS.map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => {
                          haptic.select()
                          setTopic(item.key)
                        }}
                        className={[
                          'rounded-full border px-3 py-1.5 text-xs transition-colors',
                          topic === item.key
                            ? 'border-primary/60 bg-primary/15 text-foreground'
                            : 'border-border/70 text-muted-foreground hover:bg-secondary/50',
                        ].join(' ')}
                      >
                        {item.labelFa}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="subject" className="text-xs text-muted-foreground">
                    {'\u0639\u0646\u0648\u0627\u0646'}
                  </label>
                  <Input
                    id="subject"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder={'\u062e\u0644\u0627\u0635\u0647\u200c\u06cc \u06a9\u0648\u062a\u0627\u0647 \u0645\u0634\u06a9\u0644'}
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="message" className="text-xs text-muted-foreground">
                    {'\u0634\u0631\u062d \u0645\u0634\u06a9\u0644'}
                  </label>
                  <Textarea
                    id="message"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    placeholder={'\u0647\u0631\u0686\u0647 \u062f\u0642\u06cc\u0642\u200c\u062a\u0631 \u0628\u0646\u0648\u06cc\u0633\u06cc\u062f\u060c \u0633\u0631\u06cc\u0639\u200c\u062a\u0631 \u062d\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
                    rows={5}
                  />
                  {/*
                    A live counter rather than an error after submission. The
                    minimum exists because one-line tickets cost a round trip
                    of questions before support can do anything.
                  */}
                  <p className="nums text-[11px] text-muted-foreground">
                    {messageLength < MIN_MESSAGE
                      ? '\u062f\u0633\u062a\u200c\u06a9\u0645 ' +
                        faNumber(MIN_MESSAGE) +
                        ' \u062d\u0631\u0641 \u0628\u0646\u0648\u06cc\u0633\u06cc\u062f'
                      : '\u0622\u0645\u0627\u062f\u0647\u200c\u06cc \u0627\u0631\u0633\u0627\u0644'}
                  </p>
                </div>

                {formError ? (
                  <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-loose text-destructive">
                    {formError}
                  </p>
                ) : null}

                <Button full loading={busy} disabled={!valid} onClick={() => void submit()}>
                  {'\u0627\u0631\u0633\u0627\u0644'}
                </Button>
              </div>
            </SheetContent>
          </Sheet>
        }
      />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonList count={3} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={MessageSquarePlus}
          title={'\u062a\u06cc\u06a9\u062a\u06cc \u0646\u062f\u0627\u0631\u06cc\u062f'}
          description={'\u0627\u06af\u0631 \u0645\u0634\u06a9\u0644\u06cc \u0647\u0633\u062a\u060c \u062a\u06cc\u06a9\u062a \u0628\u0632\u0646\u06cc\u062f. \u0645\u0639\u0645\u0648\u0644\u0627\u064b \u0632\u06cc\u0631 \u06cc\u06a9 \u0633\u0627\u0639\u062a \u067e\u0627\u0633\u062e \u0645\u06cc\u200c\u062f\u0647\u06cc\u0645.'}
        />
      ) : (
        <ul className="space-y-2 pb-4">
          {data.map((ticket) => {
            const meta = STATE_META[ticket.state]
            return (
              <li key={ticket.ticketId}>
                <Link href={`/support/${ticket.ticketId}`}>
                  <Card className="space-y-2 p-3 transition-colors hover:border-border">
                    <div className="flex items-start justify-between gap-3">
                      <p className="min-w-0 flex-1 truncate text-sm font-medium">
                        {ticket.topicFa}
                      </p>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {ticket.unreadCount > 0 ? (
                          <Badge variant="destructive" className="nums px-1.5">
                            {faNumber(ticket.unreadCount)}
                          </Badge>
                        ) : null}
                        <Badge variant={meta.variant}>{meta.labelFa}</Badge>
                      </div>
                    </div>

                    <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                      <span className="nums truncate">{ticket.reference}</span>
                      <span className="shrink-0">
                        {faRelative(ticket.lastReplyAt ?? ticket.createdAt)}
                      </span>
                    </div>
                  </Card>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
