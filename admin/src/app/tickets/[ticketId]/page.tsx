'use client'

import * as React from 'react'
import { useParams } from 'next/navigation'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faDateTime } from '@/lib/fa'
import { TICKET_STATE } from '@/lib/labels'
import type { AdminTicketMessage, AdminTicketRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field, Textarea } from '@/components/ui/input'
import { SkeletonCards } from '@/components/ui/skeleton'

/**
 * Ticket thread.
 *
 * Operator messages are aligned to the start of the reading direction and
 * customer messages to the end, the mirror of the customer's own view in the
 * bot. Whoever is reading always finds "the other side" on the same edge.
 *
 * Replying moves the ticket to `answered` server-side; there is no separate
 * "mark as answered" button, because a state that can drift from the actual
 * conversation is a state that will drift.
 */
export default function TicketDetailPage() {
  const params = useParams<{ ticketId: string }>()
  const { can } = useSession()
  const ticketId = params.ticketId

  const [reply, setReply] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  // Two calls: the ticket and its thread are separate endpoints. This asked
  // for {ticket, messages} from the messages endpoint, which returns neither.
  const ticketQuery = useSWR<AdminTicketRow>(['ticket', ticketId], () => api.ticket(ticketId))
  const thread = useSWR<{ items: AdminTicketMessage[] }>(
    ['ticket-messages', ticketId],
    () => api.ticketMessages(ticketId),
  )

  if (!can('tickets.view')) return <ForbiddenState permission="tickets.view" />

  const send = async () => {
    setBusy(true)
    setFailure(null)
    try {
      await api.replyToTicket(ticketId, reply.trim())
      setReply('')
      await thread.mutate()
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  if ((thread.error ?? ticketQuery.error)) {
    return (
      <ErrorState
        messageFa={(thread.error ?? ticketQuery.error) instanceof ApiError ? (thread.error ?? ticketQuery.error).messageFa : ''}
        offline={(thread.error ?? ticketQuery.error) instanceof ApiError && (thread.error ?? ticketQuery.error).status === 0}
        onRetry={() => thread.mutate()}
      />
    )
  }

  if (thread.isLoading || ticketQuery.isLoading || !thread.data || !ticketQuery.data)
    return <SkeletonCards count={3} />

  const ticket = ticketQuery.data
  const messages = thread.data.items
  const meta = TICKET_STATE[ticket.state]
  const closed = ticket.state === 'closed'
  const replyValid = reply.trim().length >= 2

  return (
    <>
      <PageHeader
        breadcrumb={{ href: '/tickets', labelFa: '\u062a\u06cc\u06a9\u062a\u200c\u0647\u0627' }}
        title={ticket.subjectFa}
        description={'\u06a9\u0627\u0631\u0628\u0631 ' + ticket.userId + ' \u00b7 ' + ticket.reference}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant={meta.tone} dot>
              {meta.fa}
            </Badge>
            {!closed && can('tickets.close') ? (
              <Button
                variant="outline"
                onClick={async () => {
                  await api.closeTicket(ticketId)
                  thread.mutate()
                }}
              >
                {'\u0628\u0633\u062a\u0646 \u062a\u06cc\u06a9\u062a'}
              </Button>
            ) : null}
          </div>
        }
      />

      <Card>
        <CardContent className="space-y-3">
          {messages.map((message) => {
            // `kind` is the side of the conversation - see domain/support/enums.py.
            const fromOperator = message.kind === 'support' || message.kind === 'note'
            return (
              <div
                key={message.messageId}
                className={'flex ' + (fromOperator ? 'justify-start' : 'justify-end')}
              >
                <div
                  className={
                    'max-w-[80%] rounded-lg px-3 py-2 text-2xs ' +
                    (fromOperator
                      ? 'bg-primary/15 text-foreground'
                      : 'border border-border bg-muted/50 text-foreground')
                  }
                >
                  <p className="mb-1 text-muted-foreground">
                    {(fromOperator ? '\u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc' : '\u06a9\u0627\u0631\u0628\u0631') +
                      ' \u00b7 ' +
                      faDateTime(message.createdAt)}
                  </p>
                  <p className="whitespace-pre-wrap leading-7">{message.bodyFa}</p>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {can('tickets.reply') && !closed ? (
        <Card>
          <CardContent className="space-y-2">
            <Field label={'\u067e\u0627\u0633\u062e'}>
              <Textarea
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                rows={4}
                placeholder={'\u067e\u0627\u0633\u062e \u062e\u0648\u062f \u0631\u0627 \u0628\u0646\u0648\u06cc\u0633\u06cc\u062f\u2026'}
              />
            </Field>

            {failure ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
                {failure}
              </p>
            ) : null}

            <div className="flex justify-end">
              <Button loading={busy} disabled={!replyValid} onClick={send}>
                {'\u0627\u0631\u0633\u0627\u0644 \u067e\u0627\u0633\u062e'}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {closed ? (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-2xs text-muted-foreground">
          {'\u0627\u06cc\u0646 \u062a\u06cc\u06a9\u062a \u0628\u0633\u062a\u0647 \u0634\u062f\u0647 \u0627\u0633\u062a. \u06a9\u0627\u0631\u0628\u0631 \u0645\u06cc\u200c\u062a\u0648\u0627\u0646\u062f \u062a\u06cc\u06a9\u062a \u062a\u0627\u0632\u0647\u200c\u0627\u06cc \u0628\u0627\u0632 \u06a9\u0646\u062f.'}
        </p>
      ) : null}
    </>
  )
}
