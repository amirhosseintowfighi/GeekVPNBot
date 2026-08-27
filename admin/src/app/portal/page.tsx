'use client'

import * as React from 'react'
import useSWR from 'swr'

import { ApiError, api } from '@/lib/api'
import { faNumber, toman } from '@/lib/fa'
import type { ResellerLedgerRow, ResellerPriceRow, ResellerSelf } from '@/lib/types'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { useSession } from '@/components/shell/session'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { SkeletonCards } from '@/components/ui/skeleton'

/**
 * What a reseller sees when they sign in.
 *
 * Every other section of the panel resolves to a permission they do not hold,
 * so without this page a reseller signed in successfully and landed on an empty
 * console - which was the state this shipped in.
 *
 * Their prices are the point of the screen. They see what each package costs
 * them and set what they charge, side by side, because that gap is the only
 * number they are actually deciding.
 */
export default function PortalPage() {
  const { can } = useSession()

  const { data: me, error, mutate: reloadMe } = useSWR<ResellerSelf>('reseller-me', () =>
    api.me(),
  )
  const { data: plans, mutate: reloadPlans } = useSWR<ResellerPriceRow[]>(
    'reseller-my-plans',
    () => api.myPlans(),
  )
  const { data: ledger } = useSWR<ResellerLedgerRow[]>('reseller-my-ledger', () =>
    api.myLedger(),
  )

  if (!can('reseller.portal')) return <ForbiddenState permission="reseller.portal" />
  if (error) {
    return (
      <ErrorState
        messageFa={error instanceof ApiError ? error.messageFa : 'اطلاعات نمایندگی بارگذاری نشد.'}
        onRetry={() => void reloadMe()}
      />
    )
  }
  if (!me) return <SkeletonCards />

  return (
    <div className="space-y-6">
      <PageHeader
        title={me.nameFa}
        description={`تخفیف شما روی همهٔ پلن‌ها: ${faNumber(me.discountPercent)}٪`}
      />

      <Card className="p-4">
        <div className="text-sm text-muted-foreground">اعتبار</div>
        <div
          className={`text-3xl font-semibold ${me.inArrears ? 'text-destructive' : ''}`}
        >
          {toman(me.balance)}
        </div>
        {me.inArrears ? (
          <p className="mt-2 text-sm text-destructive">
            موجودی منفی است، بنابراین سرویس مشتریان شما تا تسویه غیرفعال شده و
            بلافاصله بعد از مثبت شدن موجودی برمی‌گردد.
          </p>
        ) : null}
      </Card>

      <BotCard me={me} onChanged={() => void reloadMe()} />

      <PricesCard rows={plans ?? []} onSaved={() => void reloadPlans()} />

      {ledger?.length ? (
        <Card className="p-4">
          <div className="mb-3 text-sm font-medium">گردش اعتبار</div>
          <div className="divide-y text-sm">
            {ledger.map((row, index) => (
              <div key={index} className="flex justify-between gap-3 py-2">
                <span className="min-w-0 truncate">{row.descriptionFa}</span>
                <span className={row.amount < 0 ? 'text-destructive' : 'text-emerald-600'}>
                  {row.amount < 0 ? '−' : '+'}
                  {toman(Math.abs(row.amount))}
                </span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}

function BotCard({ me, onChanged }: { me: ResellerSelf; onChanged: () => void }) {
  const [token, setToken] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.setMyBot(token.trim())
      setToken('')
      onChanged()
    } catch (thrown) {
      setError(
        thrown instanceof ApiError ? thrown.messageFa : 'تلگرام این توکن را نپذیرفت.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        ربات اختصاصی شما
        {me.hasBot ? (
          <Badge variant="success">{me.botUsername ?? 'فعال'}</Badge>
        ) : (
          <Badge variant="muted">تنظیم نشده</Badge>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        از <span dir="ltr">@BotFather</span> یک ربات بسازید و توکنش را اینجا وارد
        کنید. مشتریان شما با همان ربات و با قیمت‌های شما خرید می‌کنند.
      </p>
      {/* In the panel and never in a chat: a bot token is a full credential,
          and one typed into Telegram is in somebody's message history forever. */}
      <Field label="توکن ربات" hint="فقط اینجا وارد کنید، هرگز در چت">
        <Input
          dir="ltr"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="123456:ABC-DEF..."
        />
      </Field>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <Button disabled={token.trim().length < 20 || busy} onClick={() => void save()}>
        {busy ? 'در حال بررسی…' : me.hasBot ? 'جایگزینی ربات' : 'اتصال ربات'}
      </Button>
    </Card>
  )
}

function PricesCard({
  rows,
  onSaved,
}: {
  rows: ResellerPriceRow[]
  onSaved: () => void
}) {
  const [draft, setDraft] = React.useState<Record<string, string>>({})
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    setDraft(Object.fromEntries(rows.map((row) => [row.planId, String(row.retail)])))
  }, [rows])

  if (!rows.length) {
    return (
      <Card className="p-4 text-sm text-muted-foreground">
        فعلاً پلنی برای فروش موجود نیست.
      </Card>
    )
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const prices: Record<string, number> = {}
      for (const [planId, raw] of Object.entries(draft)) {
        const value = Number(raw)
        if (Number.isInteger(value) && value >= 0) prices[planId] = value
      }
      await api.setMyRetail(prices)
      onSaved()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ذخیره نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="text-sm font-medium">قیمت‌های شما</div>
      <p className="text-sm text-muted-foreground">
        «قیمت خرید» چیزی است که از ما می‌خرید. «قیمت فروش» را خودتان تعیین
        می‌کنید — هر عددی که بخواهید.
      </p>
      <div className="max-h-96 overflow-y-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="p-2 text-right font-medium">پلن</th>
              <th className="p-2 text-right font-medium">قیمت خرید</th>
              <th className="p-2 text-right font-medium">قیمت فروش</th>
              <th className="p-2 text-right font-medium">سود</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => {
              const retail = Number(draft[row.planId] ?? row.retail)
              const margin = Number.isFinite(retail) ? retail - row.cost : 0
              return (
                <tr key={row.planId}>
                  <td className="p-2">
                    {row.name}
                    <div className="text-xs text-muted-foreground">
                      {faNumber(row.durationDays)} روز
                    </div>
                  </td>
                  <td className="p-2 text-muted-foreground">{toman(row.cost, false)}</td>
                  <td className="p-2">
                    <Input
                      dir="ltr"
                      inputMode="numeric"
                      value={draft[row.planId] ?? ''}
                      onChange={(event) =>
                        setDraft({ ...draft, [row.planId]: event.target.value })
                      }
                    />
                  </td>
                  <td
                    className={`p-2 ${margin < 0 ? 'text-destructive' : 'text-emerald-600'}`}
                  >
                    {toman(margin, false)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <Button disabled={busy} onClick={() => void save()}>
        ذخیرهٔ قیمت‌ها
      </Button>
    </Card>
  )
}
