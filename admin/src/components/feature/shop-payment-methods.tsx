'use client'

import * as React from 'react'
import useSWR from 'swr'

import { ApiError, api } from '@/lib/api'
import type { ShopPaymentMethods } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

const PROVIDER_LABEL: Record<string, string> = {
  zarinpal: 'زرین‌پال',
  zibal: 'زیبال',
  aqayepardakht: 'آقای پرداخت',
}

/**
 * A reseller's own payment destinations.
 *
 * It calls the reseller's endpoints, not the operator's. A reseller holds
 * neither `payments.read` nor `payments.approve` - deliberately, since those
 * open every admin payment screen - so the admin routes would have answered
 * 403 on a card they own.
 *
 * Nothing is required. A shop that adds only a card offers only card-to-card,
 * and the bot shows exactly what is configured: a button that leads to an
 * apology is worse than no button.
 */
export function ShopPaymentMethodsCard() {
  const { data, mutate } = useSWR<ShopPaymentMethods>('reseller-my-methods', () =>
    api.myPaymentMethods(),
  )
  const [card, setCard] = React.useState({ cardNumber: '', holderFa: '', bankFa: '' })
  const [crypto, setCrypto] = React.useState({
    address: '',
    network: 'trc20',
    asset: 'USDT',
  })
  const [gateway, setGateway] = React.useState({ provider: 'zarinpal', merchantId: '' })
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      await mutate()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ثبت نشد.')
    } finally {
      setBusy(false)
    }
  }

  const digits = card.cardNumber.replace(/[^0-9]/g, '')

  return (
    <Card className="space-y-4 p-4">
      <div className="text-sm font-medium">روش‌های پرداخت شما</div>
      <p className="text-sm text-muted-foreground">
        مشتریان شما به این‌ها پرداخت می‌کنند، نه به حساب‌های ما. فقط همان‌هایی
        که ثبت کرده‌اید در ربات شما نشان داده می‌شوند.
      </p>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="space-y-2">
        {data?.cards.map((row) => (
          <MethodRow
            key={row.id}
            title={row.cardNumber}
            subtitle={row.holderFa + ' · ' + row.bankFa}
            active={row.active}
            onToggle={(next) => run(() => api.setMyMethodActive('card', row.id, next))}
          />
        ))}
        {data?.crypto.map((row) => (
          <MethodRow
            key={row.id}
            title={row.address}
            subtitle={row.network + ' · ' + row.asset}
            active={row.active}
            onToggle={(next) => run(() => api.setMyMethodActive('crypto', row.id, next))}
          />
        ))}
        {data?.gateways.map((row) => (
          <MethodRow
            key={row.id}
            title={PROVIDER_LABEL[row.provider] ?? row.provider}
            subtitle={row.hasMerchantId ? 'شناسه ثبت شده' : 'بدون شناسه'}
            active={row.active}
            onToggle={(next) => run(() => api.setMyMethodActive('gateway', row.id, next))}
          />
        ))}
      </div>

      <div className="space-y-2 rounded-md border p-3">
        <div className="text-sm font-medium">افزودن کارت</div>
        <Input
          dir="ltr"
          inputMode="numeric"
          value={card.cardNumber}
          onChange={(event) => setCard({ ...card, cardNumber: event.target.value })}
          placeholder="6037991199119911"
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <Input
            value={card.holderFa}
            onChange={(event) => setCard({ ...card, holderFa: event.target.value })}
            placeholder="به نام"
          />
          <Input
            value={card.bankFa}
            onChange={(event) => setCard({ ...card, bankFa: event.target.value })}
            placeholder="بانک"
          />
        </div>
        <Button
          disabled={
            busy || digits.length < 16 || !card.holderFa.trim() || !card.bankFa.trim()
          }
          onClick={() =>
            void run(async () => {
              await api.addMyCard({
                cardNumber: digits,
                holderFa: card.holderFa.trim(),
                bankFa: card.bankFa.trim(),
              })
              setCard({ cardNumber: '', holderFa: '', bankFa: '' })
            })
          }
        >
          افزودن
        </Button>
      </div>

      <div className="space-y-2 rounded-md border p-3">
        <div className="text-sm font-medium">افزودن آدرس رمزارز</div>
        <Input
          dir="ltr"
          value={crypto.address}
          onChange={(event) => setCrypto({ ...crypto, address: event.target.value })}
          placeholder="TXyz..."
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <Input
            dir="ltr"
            value={crypto.network}
            onChange={(event) => setCrypto({ ...crypto, network: event.target.value })}
          />
          <Input
            dir="ltr"
            value={crypto.asset}
            onChange={(event) => setCrypto({ ...crypto, asset: event.target.value })}
          />
        </div>
        <Button
          disabled={busy || crypto.address.trim().length < 8}
          onClick={() =>
            void run(async () => {
              await api.addMyCrypto(crypto)
              setCrypto({ address: '', network: 'trc20', asset: 'USDT' })
            })
          }
        >
          افزودن
        </Button>
      </div>

      <div className="space-y-2 rounded-md border p-3">
        <div className="text-sm font-medium">افزودن درگاه بانکی</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {/* The styled Select, not a bare `<select>`. The native one paints
              its option list with the operating system's colours, which in a
              dark panel is white text on white. */}
          <Select
            value={gateway.provider}
            onValueChange={(value) => setGateway({ ...gateway, provider: value })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(PROVIDER_LABEL).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* Goes in and never comes back: it identifies the shop to the
              provider, and it is the only thing between somebody and a payment
              request billed to that shop. */}
          <Input
            dir="ltr"
            value={gateway.merchantId}
            onChange={(event) =>
              setGateway({ ...gateway, merchantId: event.target.value })
            }
            placeholder="شناسهٔ پذیرنده"
          />
        </div>
        <Button
          disabled={busy || gateway.merchantId.trim().length < 4}
          onClick={() =>
            void run(async () => {
              await api.addMyGateway({
                provider: gateway.provider,
                merchantId: gateway.merchantId.trim(),
              })
              setGateway({ provider: gateway.provider, merchantId: '' })
            })
          }
        >
          افزودن
        </Button>
      </div>
    </Card>
  )
}

function MethodRow({
  title,
  subtitle,
  active,
  onToggle,
}: {
  title: string
  subtitle: string
  active: boolean
  onToggle: (next: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm">
      <div className="min-w-0">
        <code dir="ltr" className="break-all">
          {title}
        </code>
        <div className="text-xs text-muted-foreground">{subtitle}</div>
      </div>
      <Switch checked={active} onCheckedChange={onToggle} />
    </div>
  )
}
