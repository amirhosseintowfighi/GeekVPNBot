'use client'

import * as React from 'react'
import { useParams } from 'next/navigation'
import { Send } from 'lucide-react'
import useSWR from 'swr'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonList } from '@/components/ui/skeleton'
import { api, ApiError, fetcher } from '@/lib/api'
import { faDateTime } from '@/lib/fa'
import { haptic } from '@/lib/telegram'
import { cn } from '@/lib/utils'
import type { TicketCard, TicketMessage } from '@/lib/types'

const MIN_MESSAGE = 10

/**
 * One support ticket, as a conversation.
 *
 * The list linked here and this page did not exist, so every ticket a customer
 * tapped answered "404 - this page could not be found" inside Telegram, where
 * there is no address bar to go back from.
 *
 * It polls while the ticket is open. Support replies arrive in the bot chat as
 * well, so this is the second place they land rather than the only one - but
 * someone who opened the Mini App to read a thread should not have to leave it
 * to find out an answer came.
 */
export default function TicketPage() {
  const params = useParams<{ ticketId: string }>()
  const ticketId = params.ticketId

  const [body, setBody] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)

  const tickets = useSWR<TicketCard[]>('/api/miniapp/tickets', fetcher)
  const { data, error, mutate } = useSWR<TicketMessage[]>(
    `/api/miniapp/tickets/${ticketId}/messages`,
    fetcher,
    { refreshInterval: 20_000 },
  )

  const ticket = tickets.data?.find((item) => item.ticketId === ticketId)
  const closed = ticket?.state === 'closed'

  async function send() {
    const text = body.trim()
    if (text.length < MIN_MESSAGE) {
      setFormError(
        'پیام کوتاه است. کمی بیشتر توضیح بدهید.',
      )
      return
    }
    setBusy(true)
    setFormError(null)
    try {
      await api.replyToTicket(ticketId, text)
      setBody('')
      haptic.notify('success')
      await mutate()
    } catch (err) {
      haptic.notify('error')
      setFormError(
        err instanceof ApiError
          ? err.messageFa
          : 'ارسال پیام ممکن نشد.',
      )
    } finally {
      setBusy(false)
    }
  }

  if (error instanceof ApiError && !data) {
    return (
      <>
        <PageHeader title={'گفتگو'} />
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
        <PageHeader title={'گفتگو'} />
        <SkeletonList count={3} />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={ticket?.topicFa ?? 'گفتگو'}
        subtitle={ticket?.reference}
      />

      <div className="space-y-3 pb-4">
        {data.length === 0 ? (
          <EmptyState title={'هنوز پیامی نیست'} />
        ) : (
          data.map((message) => (
            <Card
              key={message.messageId}
              className={cn(
                'space-y-1.5 p-3',
                // The customer's own messages sit inset on the leading side,
                // which is how every chat in Telegram already reads.
                message.fromSupport ? 'me-6' : 'ms-6 border-primary/30 bg-primary/5',
              )}
            >
              <p className="text-xs leading-loose">{message.bodyFa}</p>
              <p className="nums text-[10px] text-muted-foreground">
                {(message.fromSupport
                  ? 'پشتیبانی'
                  : 'شما') +
                  ' · ' +
                  faDateTime(message.createdAt)}
              </p>
            </Card>
          ))
        )}

        {closed ? (
          <p className="rounded-lg bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
            {'این تیکت بسته شده است. برای موضوع تازه، تیکت جدید باز کنید.'}
          </p>
        ) : (
          <div className="space-y-2">
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={3}
              placeholder={'پاسخ شما...'}
              className="w-full rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs leading-loose outline-none focus:border-primary"
            />
            {formError ? (
              <p className="text-xs text-destructive">{formError}</p>
            ) : null}
            <Button full loading={busy} onClick={() => void send()}>
              <Send className="size-4" aria-hidden />
              {'ارسال'}
            </Button>
          </div>
        )}
      </div>
    </>
  )
}
