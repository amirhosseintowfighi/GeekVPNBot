'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import type { CryptoRow } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

/**
 * Crypto wallets for one shop.
 *
 * Lifted out of the reseller drawer, where it had been a private function
 * taking a required `resellerId` - so the one shop it could not configure was
 * ours. Same story as `GatewayAccounts`: a screen that exists for every
 * storefront except the operator's own.
 *
 * `resellerId` omitted means the platform. One component and two mounts rather
 * than two copies, because two copies are two places for the validation and
 * the wording to drift.
 */
export function CryptoAccounts({
  resellerId,
  writable,
}: {
  resellerId?: string
  writable: boolean
}) {
  const { data, mutate } = useSWR<CryptoRow[]>(['crypto', resellerId ?? 'platform'], () =>
    api.resellerCrypto(resellerId),
  )
  const [address, setAddress] = React.useState('')
  const [network, setNetwork] = React.useState('trc20')
  const [asset, setAsset] = React.useState('USDT')
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  const valid = address.trim().length >= 8 && network.trim().length >= 2

  const add = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.addResellerCrypto(resellerId, {
        address: address.trim(),
        network: network.trim(),
        asset: asset.trim() || 'USDT',
      })
      setAddress('')
      await mutate()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ثبت آدرس انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm leading-loose text-muted-foreground">
        {resellerId
          ? 'اگه هیچ آدرسی ثبت نشه، گزینهٔ رمزارز تو ربات این نماینده نشون داده نمی‌شه — همون قاعدهٔ کارت‌ها.'
          : 'اگه هیچ آدرسی ثبت نشه، گزینهٔ رمزارز تو ربات نشون داده نمی‌شه — همون قاعدهٔ کارت‌ها.'}
      </p>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">هنوز آدرسی ثبت نشده.</p>
      ) : (
        <div className="divide-y rounded-md border text-sm">
          {data.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 p-2">
              <div className="min-w-0">
                <code dir="ltr" className="break-all">
                  {row.address}
                </code>
                <div className="text-xs text-muted-foreground">
                  {row.network} · {row.asset}
                </div>
              </div>
              {writable ? (
                <Switch
                  checked={row.active}
                  onCheckedChange={(next) => {
                    void api.setCryptoActive(row.id, next).then(() => mutate())
                  }}
                />
              ) : null}
            </div>
          ))}
        </div>
      )}

      {writable ? (
        <div className="space-y-3 rounded-md border p-3">
          <Field label="آدرس کیف پول">
            <Input
              dir="ltr"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="TXyz..."
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="شبکه" hint="مثلاً trc20">
              <Input
                dir="ltr"
                value={network}
                onChange={(event) => setNetwork(event.target.value)}
              />
            </Field>
            <Field label="ارز">
              <Input dir="ltr" value={asset} onChange={(event) => setAsset(event.target.value)} />
            </Field>
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button disabled={!valid || busy} onClick={() => void add()}>
            افزودن آدرس
          </Button>
        </div>
      ) : null}
    </div>
  )
}
