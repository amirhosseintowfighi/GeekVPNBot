'use client'

import * as React from 'react'
import { useParams } from 'next/navigation'
import { Send } from 'lucide-react'
import useSWR from 'swr'

import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState } from '@/components/shell/states'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
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
        'پیام کوتاهه. یه کم بیشتر توضیح بده.',
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
          : 'پیام فرستاده نشد.',
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
            <div
              key={message.messageId}
              className={cn(
                'space-y-1.5 rounded-3xl p-4',
                // The customer's own messages sit inset on the leading side,
                // which is how every chat in Telegram already reads; navy for
                // "you", milky glass for support.
                message.fromSupport ? 'glass me-8 rounded-tr-[6px]' : 'navy-panel ms-8 rounded-tl-[6px]',
              )}
            >
              <p className="whitespace-pre-wrap text-sm leading-loose">{message.bodyFa}</p>
              <p className="nums text-xs text-muted-foreground">
                {(message.fromSupport
                  ? 'پشتیبانی'
                  : 'تو') +
                  ' · ' +
                  faDateTime(message.createdAt)}
              </p>
            </div>
          ))
        )}

        {closed ? (
          <p className="soft rounded-[14px] px-3 py-2 text-xs text-muted-foreground">
            {'این تیکت بسته شده. برای موضوع تازه، یه تیکت جدید بزن.'}
          </p>
        ) : (
          <div className="space-y-2">
            <Textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={3}
              placeholder={'جوابت...'}
              aria-label={'جوابت'}
            />
            {formError ? (
              <p role="alert" className="rounded-2xl bg-destructive-soft px-4 py-2.5 text-[13px] text-destructive-ink">{formError}</p>
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
