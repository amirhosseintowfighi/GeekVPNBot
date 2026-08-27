'use client'

import * as React from 'react'
import useSWR from 'swr'

import { ApiError, api } from '@/lib/api'
import type { GatewayRow } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

const PROVIDERS = [
  { value: 'zarinpal', label: 'زرین‌پال' },
  { value: 'zibal', label: 'زیبال' },
  { value: 'aqayepardakht', label: 'آقای پرداخت' },
] as const

const LABEL: Record<GatewayRow['provider'], string> = {
  zarinpal: 'زرین‌پال',
  zibal: 'زیبال',
  aqayepardakht: 'آقای پرداخت',
}

/**
 * Online payment providers for one shop.
 *
 * Shared by the operator's drawer and the reseller's own panel: it is the same
 * screen either way, and the only difference is whose shop `resellerId` names.
 *
 * The merchant id goes in and never comes back. A configured provider shows as
 * configured and nothing more, which is everything anybody needs in order to
 * tell it from a blank one.
 */
export function GatewayAccounts({
  resellerId,
  writable,
}: {
  resellerId?: string
  writable: boolean
}) {
  const { data, mutate } = useSWR<GatewayRow[]>(['gateways', resellerId ?? 'platform'], () =>
    api.gateways(resellerId),
  )
  const [provider, setProvider] = React.useState<string>('zarinpal')
  const [merchantId, setMerchantId] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const add = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.addGateway({ provider, merchantId: merchantId.trim(), resellerId })
      setMerchantId('')
      await mutate()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ثبت درگاه انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        درگاه بانکی. اگر هیچ‌کدام فعال نباشد، گزینه‌اش در ربات نمایش داده
        نمی‌شود — همان قاعدهٔ کارت و رمزارز.
      </p>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">هنوز درگاهی تنظیم نشده.</p>
      ) : (
        <div className="divide-y rounded-md border text-sm">
          {data.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 p-2">
              <div>
                {LABEL[row.provider]}
                <div className="text-xs text-muted-foreground">
                  {row.hasMerchantId ? 'شناسه ثبت شده' : 'بدون شناسه'}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {row.active ? (
                  <Badge variant="success">فعال</Badge>
                ) : (
                  <Badge variant="muted">غیرفعال</Badge>
                )}
                {writable ? (
                  <Switch
                    checked={row.active}
                    onCheckedChange={(next) => {
                      void api.setGatewayActive(row.id, next).then(() => mutate())
                    }}
                  />
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}

      {writable ? (
        <div className="space-y-3 rounded-md border p-3">
          <Field label="درگاه">
            <Select value={provider} onValueChange={setProvider}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {/* Goes in and never comes back: it identifies the shop to the
              provider, and it is the only thing between somebody and a payment
              request billed to that shop. */}
          <Field
            label="شناسهٔ پذیرنده"
            hint="مرچنت‌کد زرین‌پال، مرچنت زیبال، یا پین آقای پرداخت"
          >
            <Input
              dir="ltr"
              value={merchantId}
              onChange={(event) => setMerchantId(event.target.value)}
            />
          </Field>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button disabled={merchantId.trim().length < 4 || busy} onClick={() => void add()}>
            افزودن درگاه
          </Button>
        </div>
      ) : null}
    </div>
  )
}
