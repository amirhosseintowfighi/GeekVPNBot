'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Copy, Handshake } from 'lucide-react'

import { ApiError, api } from '@/lib/api'
import { faDate, faNumber } from '@/lib/fa'
import type { ApprovedApplication, ResellerApplicationRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
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

/**
 * People asking to sell under their own name.
 *
 * Above the reseller list rather than on a screen of its own: an application is
 * somebody waiting for an answer, and a queue on a page nobody opens is a queue
 * nobody answers.
 *
 * Approving is a dialog because of what it returns. The one-time link is the
 * only place that secret ever exists in the open, and it has to be copied
 * before the dialog closes - an operator who dismisses it issues a new one
 * rather than recovering this.
 */
export function ResellerApplications({ onApproved }: { onApproved: () => void }) {
  const { can } = useSession()
  const [deciding, setDeciding] = React.useState<ResellerApplicationRow | null>(null)

  const { data, mutate } = useSWR<ResellerApplicationRow[]>('reseller-applications', () =>
    api.resellerApplications(),
  )

  if (!can('resellers.read') || !data?.length) return null

  return (
    <>
      <Card className="border-primary/40 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Handshake className="size-4" />
          درخواست‌های نمایندگی
          <span className="text-muted-foreground">({faNumber(data.length)})</span>
        </div>
        <div className="space-y-2">
          {data.map((row) => (
            <div
              key={row.id}
              className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm"
            >
              <div className="min-w-0">
                <div className="font-medium">{row.nameFa}</div>
                <div className="text-xs text-muted-foreground">
                  {row.contactFa ?? '—'} · {faDate(row.createdAt)}
                </div>
              </div>
              {can('resellers.write') ? (
                <Button size="sm" onClick={() => setDeciding(row)}>
                  بررسی
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      </Card>

      {deciding ? (
        <DecisionDialog
          application={deciding}
          onClose={() => setDeciding(null)}
          onDone={() => {
            void mutate()
            onApproved()
          }}
        />
      ) : null}
    </>
  )
}

function DecisionDialog({
  application,
  onClose,
  onDone,
}: {
  application: ResellerApplicationRow
  onClose: () => void
  onDone: () => void
}) {
  const [discount, setDiscount] = React.useState('20')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [approved, setApproved] = React.useState<ApprovedApplication | null>(null)
  const [copied, setCopied] = React.useState(false)

  const percent = Number(discount)
  const valid = Number.isInteger(percent) && percent >= 0 && percent <= 90

  const link = approved
    ? `${window.location.origin}/set-password?a=${approved.adminId}&t=${approved.setupToken}`
    : ''

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      onDone()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  if (approved) {
    return (
      <Dialog open onOpenChange={onClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>نمایندگی تأیید شد</DialogTitle>
            <DialogDescription>
              این لینک را برایشان بفرستید تا رمز پنلشان را خودشان بسازند. یک‌بار
              مصرف است و تا ۲۴ ساعت اعتبار دارد — بعد از بستن این پنجره دوباره
              قابل دیدن نیست.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-3">
            <div className="rounded-md border p-3 text-sm">
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">نام کاربری</span>
                <code dir="ltr">{approved.username}</code>
              </div>
              <div className="mt-2 break-all text-xs" dir="ltr">
                {link}
              </div>
            </div>
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                void navigator.clipboard
                  .writeText(link)
                  .then(() => setCopied(true))
                  // A browser that refuses clipboard access is not worth an
                  // error banner: the link is on screen and selectable.
                  .catch(() => setCopied(false))
              }}
            >
              <Copy className="size-4" />
              {copied ? 'کپی شد' : 'کپی لینک'}
            </Button>
          </DialogBody>
          <DialogFooter>
            <Button onClick={onClose}>کپی کردم، ببند</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{application.nameFa}</DialogTitle>
          <DialogDescription>
            شناسه تلگرام: {faNumber(application.telegramId)} · تماس:{' '}
            {application.contactFa ?? '—'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {application.noteFa ? (
            <p className="rounded-md border p-3 text-sm">{application.noteFa}</p>
          ) : null}
          <Field
            label="درصد تخفیف"
            hint="روی قیمت هر پلن اعمال می‌شود. بعداً هم قابل تغییر است."
          >
            <Input
              dir="ltr"
              inputMode="numeric"
              value={discount}
              onChange={(event) => setDiscount(event.target.value)}
            />
          </Field>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </DialogBody>
        <DialogFooter>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api.rejectApplication(application.id, '')
                onClose()
              })
            }
          >
            رد کن
          </Button>
          <Button
            disabled={!valid || busy}
            onClick={() =>
              void run(async () => {
                setApproved(await api.approveApplication(application.id, percent))
              })
            }
          >
            {busy ? 'در حال ثبت…' : 'تأیید نمایندگی'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
