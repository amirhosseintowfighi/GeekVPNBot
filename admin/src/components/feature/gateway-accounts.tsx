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
import { GATEWAY_PROVIDERS, GATEWAY_PROVIDER_KEYS, type GatewayProvider } from '@/lib/gateway-providers'


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
  const [provider, setProvider] = React.useState<GatewayProvider>('zarinpal')
  const [merchantId, setMerchantId] = React.useState('')
  const [labelFa, setLabelFa] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const add = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.addGateway({
        provider,
        merchantId: merchantId.trim(),
        labelFa: labelFa.trim(),
        resellerId,
      })
      setMerchantId('')
      setLabelFa('')
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
        درگاه بانکی. اگه هیچ‌کدوم فعال نباشه، گزینه‌اش تو ربات نشون داده
        نمی‌شه — همون قاعدهٔ کارت و رمزارز.
      </p>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">هنوز درگاهی تنظیم نشده.</p>
      ) : (
        <div className="divide-y rounded-md border text-sm">
          {data.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 p-2">
              <div>
                {GATEWAY_PROVIDERS[row.provider]?.label ?? row.provider}
                <div className="text-xs text-muted-foreground">
                  {row.hasMerchantId ? 'شناسه ثبت شده' : 'بدون شناسه'}
                  {row.labelFa ? ' · ' + row.labelFa : ''}
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
            <Select
              value={provider}
              onValueChange={(value) => setProvider(value as GatewayProvider)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GATEWAY_PROVIDER_KEYS.map((key) => (
                  <SelectItem key={key} value={key}>
                    {GATEWAY_PROVIDERS[key].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {/* Goes in and never comes back: it identifies the shop to the
              provider, and it is the only thing between somebody and a payment
              request billed to that shop. */}
          <Field
            label={GATEWAY_PROVIDERS[provider].field}
            hint={GATEWAY_PROVIDERS[provider].hint}
          >
            <Input
              dir="ltr"
              value={merchantId}
              onChange={(event) => setMerchantId(event.target.value)}
            />
          </Field>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Field
            label="نام دکمه در ربات"
            hint="اختیاری — خالی یعنی نام پیش‌فرض همون درگاه."
          >
            <Input
              value={labelFa}
              onChange={(event) => setLabelFa(event.target.value)}
              placeholder="مثلاً: پرداخت آنلاین"
            />
          </Field>
          <Button disabled={merchantId.trim().length < 1 || busy} onClick={() => void add()}>
            افزودن درگاه
          </Button>
        </div>
      ) : null}
    </div>
  )
}
