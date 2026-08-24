'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Plus } from 'lucide-react'

import { ApiError, api } from '@/lib/api'
import { faNumber } from '@/lib/fa'
import type { CardRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
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
import { Field, Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/**
 * The destination cards for card-to-card payments.
 *
 * The bot reads the lowest-numbered active card out of the database every time
 * it quotes a transfer, deliberately: cards rotate constantly here, and a
 * rotation has to be something support can do at 2am rather than a deploy.
 *
 * There was no endpoint and no screen, so the only way to have a card at all
 * was to write the row by hand - and with no row the bot hides card-to-card
 * entirely, which is what `payments.no_active_card` in the logs means. A fresh
 * install could not take money.
 */
export function CardsSection() {
  const { can } = useSession()
  const { data, error, mutate } = useSWR<CardRow[]>('cards', () => api.cards())
  const [editing, setEditing] = React.useState<CardRow | null>(null)
  const [creating, setCreating] = React.useState(false)

  if (!can('payments.read')) return null

  const editable = can('payments.approve')
  const cards = data ?? []
  const active = cards.filter((card) => card.active)

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{'کارت‌های مقصد'}</CardTitle>
        {editable ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="size-3.5" aria-hidden />
            {'کارت جدید'}
          </Button>
        ) : null}
      </CardHeader>

      <CardContent>
        {error ? (
          <p className="text-2xs text-destructive">
            {error instanceof ApiError ? error.messageFa : ''}
          </p>
        ) : cards.length === 0 ? (
          <p className="text-2xs text-muted-foreground">
            {'هیچ کارتی ثبت نشده، بنابراین گزینهٔ کارت‌به‌کارت به مشتری نشان داده نمی‌شود.'}
          </p>
        ) : (
          <>
            {active.length === 0 ? (
              <p className="mb-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-2xs text-warning">
                {'هیچ کارتی فعال نیست. تا یکی را فعال نکنید، کارت‌به‌کارت در دسترس نیست.'}
              </p>
            ) : null}

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{'دارنده'}</TableHead>
                  <TableHead>{'بانک'}</TableHead>
                  <TableHead>{'شماره کارت'}</TableHead>
                  <TableHead>{'ترتیب'}</TableHead>
                  <TableHead>{'فعال'}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cards.map((card) => (
                  <TableRow key={card.id}>
                    <TableCell>
                      <button
                        type="button"
                        disabled={!editable}
                        onClick={() => setEditing(card)}
                        className="text-start hover:underline disabled:no-underline"
                      >
                        {card.holderFa}
                      </button>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{card.bankFa}</TableCell>
                    <TableCell dir="ltr" className="font-mono text-2xs">
                      {card.cardNumber.replace(/(\d{4})(?=\d)/g, '$1-')}
                    </TableCell>
                    <TableCell numeric className="text-muted-foreground">
                      {faNumber(card.sortOrder)}
                    </TableCell>
                    <TableCell>
                      {/* The bot takes the lowest sort order that is active, so
                          this switch is the rotation: retire one, and the next
                          one down starts being quoted immediately. */}
                      {editable ? (
                        <Switch
                          checked={card.active}
                          onCheckedChange={async (checked) => {
                            await api.updateCard(card.id, {
                              holderFa: card.holderFa,
                              bankFa: card.bankFa,
                              cardNumber: card.cardNumber,
                              sheba: card.sheba,
                              sortOrder: card.sortOrder,
                              dailyLimit: card.dailyLimit,
                              active: checked,
                            })
                            mutate()
                          }}
                        />
                      ) : (
                        <Badge variant={card.active ? 'success' : 'muted'} dot>
                          {card.active ? 'فعال' : 'غیرفعال'}
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>

      <CardDialog
        card={editing}
        open={creating || editing !== null}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
        onSaved={() => mutate()}
      />
    </Card>
  )
}

function CardDialog({
  card,
  open,
  onClose,
  onSaved,
}: {
  card: CardRow | null
  open: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const [holderFa, setHolderFa] = React.useState('')
  const [bankFa, setBankFa] = React.useState('')
  const [cardNumber, setCardNumber] = React.useState('')
  const [sheba, setSheba] = React.useState('')
  const [sortOrder, setSortOrder] = React.useState('0')
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)

  // Reload the form whenever a different card is opened.
  React.useEffect(() => {
    setHolderFa(card?.holderFa ?? '')
    setBankFa(card?.bankFa ?? '')
    setCardNumber(card?.cardNumber ?? '')
    setSheba(card?.sheba ?? '')
    setSortOrder(String(card?.sortOrder ?? 0))
    setFailure(null)
  }, [card, open])

  const digits = cardNumber.replace(/\D/g, '')
  const complete = holderFa.trim() !== '' && bankFa.trim() !== '' && digits.length >= 16

  const submit = async () => {
    setBusy(true)
    setFailure(null)
    try {
      const body = {
        holderFa: holderFa.trim(),
        bankFa: bankFa.trim(),
        cardNumber: digits,
        sheba: sheba.trim() || null,
        sortOrder: Number(sortOrder.replace(/\D/g, '')) || 0,
        active: card?.active ?? true,
        dailyLimit: card?.dailyLimit ?? null,
      }
      if (card) await api.updateCard(card.id, body)
      else await api.createCard(body)
      onSaved()
      onClose()
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
          <DialogTitle>{card ? 'ویرایش کارت' : 'کارت جدید'}</DialogTitle>
          <DialogDescription>
            {'مشتری این شماره را می‌بیند و به آن واریز می‌کند. دقت در اینجا مستقیماً پول است.'}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-3">
          <Field label={'نام دارنده کارت'}>
            <Input value={holderFa} onChange={(event) => setHolderFa(event.target.value)} autoFocus />
          </Field>

          <Field label={'بانک'}>
            <Input value={bankFa} onChange={(event) => setBankFa(event.target.value)} />
          </Field>

          <Field label={'شماره کارت'} hint={'۱۶ رقم، بدون فاصله'}>
            <Input
              ltr
              inputMode="numeric"
              value={cardNumber}
              onChange={(event) => setCardNumber(event.target.value)}
              placeholder="6037991234567890"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label={'شبا'} hint={'اختیاری'}>
              <Input ltr value={sheba} onChange={(event) => setSheba(event.target.value)} />
            </Field>

            <Field label={'ترتیب'} hint={'کوچک‌ترین عدد فعال، همان کارتی است که نشان داده می‌شود'}>
              <Input
                ltr
                inputMode="numeric"
                value={sortOrder}
                onChange={(event) => setSortOrder(event.target.value)}
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
            {card ? 'ذخیره' : 'افزودن کارت'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
