'use client'

import * as React from 'react'
import useSWR from 'swr'

import { ApiError, api } from '@/lib/api'
import { faNumber, toman } from '@/lib/fa'
import type {
  PanelRow,
  ResellerLedgerRow,
  ResellerPriceRow,
  ResellerRow,
} from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const LEDGER_LABEL: Record<string, string> = {
  topup: 'شارژ',
  sale: 'فروش',
  refund: 'بازگشت',
  adjustment: 'اصلاح',
}

/**
 * Everything about one reseller, on four tabs.
 *
 * A reseller is configured rarely and looked at often, so the list stays
 * scannable and the editing lives here. The tabs are the four questions an
 * operator actually arrives with: how much credit do they have, what do they
 * pay, where may they sell, and what have they been doing.
 *
 * Prices are two columns rather than one. The platform sets what a package
 * costs the reseller; the reseller sets what they charge their customer. Both
 * are editable here because the first thing a new reseller asks support is to
 * set their prices for them while they work out the panel - but they are two
 * separate writes, so neither can erase the other by omission.
 */
export function ResellerDrawer({
  reseller,
  panels,
  onClose,
  onChanged,
}: {
  reseller: ResellerRow
  panels: PanelRow[]
  onClose: () => void
  onChanged: () => void
}) {
  const { can } = useSession()
  const writable = can('resellers.write')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const { data: prices, mutate: reloadPrices } = useSWR<ResellerPriceRow[]>(
    ['reseller-prices', reseller.id],
    () => api.resellerPrices(reseller.id),
  )
  const { data: ledger, mutate: reloadLedger } = useSWR<ResellerLedgerRow[]>(
    ['reseller-ledger', reseller.id],
    () => api.resellerLedger(reseller.id),
  )

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      onChanged()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {reseller.nameFa}
            {reseller.inArrears ? <Badge variant="destructive">بدهکار</Badge> : null}
          </DialogTitle>
          <DialogDescription>
            {reseller.inArrears
              ? 'موجودی منفی است، بنابراین سرویس تمام مشتریان این نماینده غیرفعال شده و با مثبت شدن موجودی خودکار برمی‌گردد.'
              : `موجودی ${toman(reseller.balance)} — تخفیف ${faNumber(reseller.discountPercent)}٪`}
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          {error ? <p className="mb-3 text-sm text-destructive">{error}</p> : null}
          <Tabs defaultValue="credit">
            <TabsList>
              <TabsTrigger value="credit">اعتبار</TabsTrigger>
              <TabsTrigger value="prices">قیمت‌ها</TabsTrigger>
              <TabsTrigger value="panels">پنل‌ها</TabsTrigger>
              <TabsTrigger value="settings">تنظیمات</TabsTrigger>
            </TabsList>

            <TabsContent value="credit">
              <CreditTab
                reseller={reseller}
                ledger={ledger ?? []}
                writable={writable && !busy}
                onAdjust={(amount, note) =>
                  run(async () => {
                    await api.adjustResellerCredit(reseller.id, amount, note)
                    await reloadLedger()
                  })
                }
              />
            </TabsContent>

            <TabsContent value="prices">
              <PricesTab
                rows={prices ?? []}
                writable={writable && !busy}
                onSaveCosts={(map) =>
                  run(async () => {
                    await api.setResellerCosts(reseller.id, map)
                    await reloadPrices()
                  })
                }
                onSaveRetail={(map) =>
                  run(async () => {
                    await api.setResellerRetail(reseller.id, map)
                    await reloadPrices()
                  })
                }
              />
            </TabsContent>

            <TabsContent value="panels">
              <PanelsTab
                panels={panels}
                selected={reseller.allowedNodeIds}
                writable={writable && !busy}
                onSave={(ids) => run(() => api.setResellerPanels(reseller.id, ids))}
              />
            </TabsContent>

            <TabsContent value="settings">
              <SettingsTab
                reseller={reseller}
                writable={writable && !busy}
                onSave={(patch) => run(() => api.updateReseller(reseller.id, patch))}
              />
            </TabsContent>
          </Tabs>
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}

function CreditTab({
  reseller,
  ledger,
  writable,
  onAdjust,
}: {
  reseller: ResellerRow
  ledger: ResellerLedgerRow[]
  writable: boolean
  onAdjust: (amount: number, note: string) => void
}) {
  const [amount, setAmount] = React.useState('')
  const [note, setNote] = React.useState('')
  const value = Number(amount)
  const valid = Number.isInteger(value) && value !== 0 && note.trim().length > 0

  return (
    <div className="space-y-4 pt-4">
      <div className="rounded-md border p-3">
        <div className="text-sm text-muted-foreground">موجودی فعلی</div>
        <div
          className={`text-2xl font-semibold ${reseller.balance < 0 ? 'text-destructive' : ''}`}
        >
          {toman(reseller.balance)}
        </div>
      </div>

      {writable ? (
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field
            label="مبلغ"
            hint="مثبت برای شارژ، منفی برای کسر. کسر می‌تواند موجودی را منفی کند."
          >
            <Input
              dir="ltr"
              inputMode="numeric"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="1000000"
            />
          </Field>
          <Field label="بابت" hint="روی دفتر اعتبار ثبت می‌شود">
            <Input value={note} onChange={(event) => setNote(event.target.value)} />
          </Field>
          <Button
            disabled={!valid}
            onClick={() => {
              onAdjust(value, note.trim())
              setAmount('')
              setNote('')
            }}
          >
            ثبت
          </Button>
        </div>
      ) : null}

      <div>
        <div className="mb-2 text-sm font-medium">دفتر اعتبار</div>
        {!ledger.length ? (
          <p className="text-sm text-muted-foreground">هنوز تراکنشی ثبت نشده.</p>
        ) : (
          <div className="divide-y rounded-md border text-sm">
            {ledger.map((row) => (
              <div key={row.id} className="flex items-center justify-between gap-3 p-2">
                <div className="min-w-0">
                  <div className="truncate">{row.descriptionFa}</div>
                  <div className="text-xs text-muted-foreground">
                    {LEDGER_LABEL[row.kind] ?? row.kind}
                  </div>
                </div>
                <div className="shrink-0 text-left">
                  <div className={row.amount < 0 ? 'text-destructive' : 'text-emerald-600'}>
                    {row.amount < 0 ? '−' : '+'}
                    {toman(Math.abs(row.amount))}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {toman(row.balanceAfter)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function PricesTab({
  rows,
  writable,
  onSaveCosts,
  onSaveRetail,
}: {
  rows: ResellerPriceRow[]
  writable: boolean
  onSaveCosts: (map: Record<string, number>) => void
  onSaveRetail: (map: Record<string, number>) => void
}) {
  // Two drafts, because the two columns are saved separately. Keyed by plan,
  // and only what the operator actually typed is sent - a plan left alone
  // keeps whatever it had.
  const [costs, setCosts] = React.useState<Record<string, string>>({})
  const [retail, setRetail] = React.useState<Record<string, string>>({})

  React.useEffect(() => {
    setCosts(Object.fromEntries(rows.map((row) => [row.planId, String(row.cost)])))
    setRetail(Object.fromEntries(rows.map((row) => [row.planId, String(row.retail)])))
  }, [rows])

  const collect = (draft: Record<string, string>) => {
    const map: Record<string, number> = {}
    for (const [planId, raw] of Object.entries(draft)) {
      const value = Number(raw)
      if (Number.isInteger(value) && value >= 0) map[planId] = value
    }
    return map
  }

  if (!rows.length) {
    return <p className="pt-4 text-sm text-muted-foreground">پلن منتشرشده‌ای وجود ندارد.</p>
  }

  return (
    <div className="space-y-3 pt-4">
      <p className="text-sm text-muted-foreground">
        ستون «قیمت خرید» را شما تعیین می‌کنید و ستون «قیمت فروش» را نماینده. هر کدام
        جداگانه ذخیره می‌شود.
      </p>
      <div className="max-h-80 overflow-y-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="p-2 text-right font-medium">پلن</th>
              <th className="p-2 text-right font-medium">قیمت عمومی</th>
              <th className="p-2 text-right font-medium">قیمت خرید</th>
              <th className="p-2 text-right font-medium">قیمت فروش</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => (
              <tr key={row.planId}>
                <td className="p-2">
                  {row.name}
                  <div className="text-xs text-muted-foreground">
                    {faNumber(row.durationDays)} روز
                  </div>
                </td>
                <td className="p-2 text-muted-foreground">{toman(row.listPrice, false)}</td>
                <td className="p-2">
                  <Input
                    dir="ltr"
                    inputMode="numeric"
                    disabled={!writable}
                    value={costs[row.planId] ?? ''}
                    onChange={(event) =>
                      setCosts({ ...costs, [row.planId]: event.target.value })
                    }
                  />
                </td>
                <td className="p-2">
                  <Input
                    dir="ltr"
                    inputMode="numeric"
                    disabled={!writable}
                    value={retail[row.planId] ?? ''}
                    onChange={(event) =>
                      setRetail({ ...retail, [row.planId]: event.target.value })
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {writable ? (
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => onSaveCosts(collect(costs))}>
            ذخیره‌ی قیمت خرید
          </Button>
          <Button variant="outline" onClick={() => onSaveRetail(collect(retail))}>
            ذخیره‌ی قیمت فروش
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function PanelsTab({
  panels,
  selected,
  writable,
  onSave,
}: {
  panels: PanelRow[]
  selected: string[]
  writable: boolean
  onSave: (ids: string[]) => void
}) {
  const [chosen, setChosen] = React.useState<string[]>(selected)

  React.useEffect(() => setChosen(selected), [selected])

  const toggle = (id: string) =>
    setChosen(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id])

  return (
    <div className="space-y-3 pt-4">
      <p className="text-sm text-muted-foreground">
        اگر هیچ‌کدام انتخاب نشود، نماینده روی همه‌ی پنل‌ها می‌تواند بفروشد — یعنی هنوز
        محدودیتی تعیین نکرده‌اید.
      </p>
      <div className="space-y-2">
        {panels.map((panel) => (
          <label
            key={panel.id}
            className="flex items-center justify-between rounded-md border p-2 text-sm"
          >
            <span>
              {panel.nameFa}
              <span className="ms-2 text-xs text-muted-foreground" dir="ltr">
                {panel.id}
              </span>
            </span>
            <Switch
              checked={chosen.includes(panel.id)}
              disabled={!writable}
              onCheckedChange={() => toggle(panel.id)}
            />
          </label>
        ))}
      </div>
      {writable ? <Button onClick={() => onSave(chosen)}>ذخیره</Button> : null}
    </div>
  )
}

function SettingsTab({
  reseller,
  writable,
  onSave,
}: {
  reseller: ResellerRow
  writable: boolean
  onSave: (patch: Record<string, unknown>) => void
}) {
  const [nameFa, setNameFa] = React.useState(reseller.nameFa)
  const [discount, setDiscount] = React.useState(String(reseller.discountPercent))
  const [contact, setContact] = React.useState(reseller.contactFa ?? '')
  const [status, setStatus] = React.useState(reseller.status)

  const percent = Number(discount)
  const valid =
    nameFa.trim().length > 0 && Number.isInteger(percent) && percent >= 0 && percent <= 90

  return (
    <div className="space-y-4 pt-4">
      <Field label="نام نمایندگی">
        <Input
          value={nameFa}
          disabled={!writable}
          onChange={(event) => setNameFa(event.target.value)}
        />
      </Field>
      <Field label="درصد تخفیف" hint="حداکثر ۹۰">
        <Input
          dir="ltr"
          inputMode="numeric"
          disabled={!writable}
          value={discount}
          onChange={(event) => setDiscount(event.target.value)}
        />
      </Field>
      <Field label="راه تماس">
        <Input
          value={contact}
          disabled={!writable}
          onChange={(event) => setContact(event.target.value)}
        />
      </Field>
      <Field
        label="تعلیق"
        hint="فروش جدید متوقف می‌شود. سرویس‌های فعلی مشتریانش دست‌نخورده می‌مانند."
      >
        <Switch
          checked={status === 'suspended'}
          disabled={!writable}
          onCheckedChange={(next) => setStatus(next ? 'suspended' : 'active')}
        />
      </Field>
      {writable ? (
        <Button
          disabled={!valid}
          onClick={() =>
            onSave({
              nameFa: nameFa.trim(),
              discountPercent: percent,
              contactFa: contact.trim() || null,
              status,
            })
          }
        >
          ذخیره
        </Button>
      ) : null}
    </div>
  )
}
