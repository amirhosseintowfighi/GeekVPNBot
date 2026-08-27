'use client'

import * as React from 'react'
import useSWR from 'swr'

import { ApiError, api } from '@/lib/api'
import { faNumber, toman } from '@/lib/fa'
import type {
  BroadcastResult,
  ResellerCustomers,
  ResellerLedgerRow,
  ResellerPriceRow,
  ResellerSelf,
  ResellerSummary,
  ResellerTopupRow,
} from '@/lib/types'
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
  const { data: summary } = useSWR<ResellerSummary>('reseller-my-summary', () =>
    api.mySummary(),
  )
  const { data: topups, mutate: reloadTopups } = useSWR<ResellerTopupRow[]>(
    'reseller-my-topups',
    () => api.myTopups(),
  )
  const { data: customers } = useSWR<ResellerCustomers>('reseller-my-customers', () =>
    api.myCustomers(),
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

      <TopupCard
        rows={topups ?? []}
        onRequested={() => {
          void reloadTopups()
          void reloadMe()
        }}
      />

      {summary ? <SummaryCards summary={summary} /> : null}

      <BrandCard me={me} onChanged={() => void reloadMe()} />

      <BotCard me={me} onChanged={() => void reloadMe()} />

      <PricesCard rows={plans ?? []} onSaved={() => void reloadPlans()} />

      <CustomersCard customers={customers} />

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


const TOPUP_STATE: Record<ResellerTopupRow['state'], string> = {
  pending: 'در انتظار تأیید',
  approved: 'تأیید شد',
  rejected: 'رد شد',
}

function TopupCard({
  rows,
  onRequested,
}: {
  rows: ResellerTopupRow[]
  onRequested: () => void
}) {
  const [amount, setAmount] = React.useState('')
  const [note, setNote] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const value = Number(amount)
  const valid = Number.isInteger(value) && value >= 10_000

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.requestTopup(value, note.trim())
      setAmount('')
      setNote('')
      onRequested()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'درخواست ثبت نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="text-sm font-medium">شارژ حساب</div>
      <p className="text-sm text-muted-foreground">
        مبلغ را واریز کنید و اینجا ثبتش کنید. بعد از تأیید، اعتبارتان بالا
        می‌رود و می‌توانید سرویس بسازید.
      </p>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="مبلغ" hint="حداقل ۱۰٬۰۰۰ تومان">
          <Input
            dir="ltr"
            inputMode="numeric"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="1000000"
          />
        </Field>
        <Field label="توضیح" hint="شماره پیگیری یا چهار رقم آخر کارتی که از آن فرستادید">
          <Input value={note} onChange={(event) => setNote(event.target.value)} />
        </Field>
        <Button disabled={!valid || busy} onClick={() => void submit()}>
          ثبت درخواست
        </Button>
      </div>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {rows.length ? (
        <div className="divide-y rounded-md border text-sm">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 p-2">
              <span>{toman(row.amount)}</span>
              <Badge
                variant={
                  row.state === 'approved'
                    ? 'success'
                    : row.state === 'rejected'
                      ? 'destructive'
                      : 'muted'
                }
              >
                {TOPUP_STATE[row.state]}
              </Badge>
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  )
}

function SummaryCards({ summary }: { summary: ResellerSummary }) {
  // Four figures, off their own ledger. Not the platform's analytics, which is
  // scoped to nothing - this screen needs four sums, not a door into everyone
  // else's numbers.
  const cards = [
    { label: 'تعداد فروش', value: faNumber(summary.sales) },
    { label: 'مجموع خرید شما', value: toman(summary.spent) },
    { label: 'مجموع شارژ', value: toman(summary.toppedUp) },
    { label: 'میانگین هر فروش', value: toman(summary.averageSale) },
  ]

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <Card key={card.label} className="p-4">
          <div className="text-sm text-muted-foreground">{card.label}</div>
          <div className="mt-1 text-xl font-semibold">{card.value}</div>
        </Card>
      ))}
    </div>
  )
}


function BrandCard({ me, onChanged }: { me: ResellerSelf; onChanged: () => void }) {
  const [brand, setBrand] = React.useState(me.brandFa)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.setMyBrand(brand.trim())
      onChanged()
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ذخیره نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="text-sm font-medium">نام کسب‌وکار شما</div>
      <p className="text-sm text-muted-foreground">
        رباتتان با همین نام به مشتریانتان سلام می‌کند و در پیام دعوت دوستان هم
        همین می‌آید.
      </p>
      <Field label="نام" hint="خالی بگذارید تا نام نمایندگی‌تان استفاده شود">
        <Input value={brand} onChange={(event) => setBrand(event.target.value)} />
      </Field>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <Button disabled={busy} onClick={() => void save()}>
        ذخیره
      </Button>
    </Card>
  )
}


function CustomersCard({ customers }: { customers: ResellerCustomers | undefined }) {
  const [message, setMessage] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [result, setResult] = React.useState<BroadcastResult | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const send = async () => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await api.myBroadcast(message.trim()))
      setMessage('')
    } catch (thrown) {
      setError(thrown instanceof ApiError ? thrown.messageFa : 'ارسال انجام نشد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-4 p-4">
      <div className="text-sm font-medium">
        مشتریان شما
        {customers ? (
          <span className="ms-2 text-muted-foreground">({faNumber(customers.total)})</span>
        ) : null}
      </div>

      {!customers?.items.length ? (
        <p className="text-sm text-muted-foreground">
          هنوز کسی رباتتان را استارت نکرده.
        </p>
      ) : (
        <div className="max-h-64 divide-y overflow-y-auto rounded-md border text-sm">
          {customers.items.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 p-2">
              <span className="min-w-0 truncate">{row.displayName}</span>
              <span className="shrink-0 text-xs text-muted-foreground" dir="ltr">
                {row.username ? '@' + row.username : faNumber(row.telegramId)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-2 border-t pt-3">
        <div className="text-sm font-medium">پیام همگانی</div>
        <p className="text-sm text-muted-foreground">
          به همهٔ مشتریانتان، از ربات خودتان. کسانی که ربات را بلاک کرده‌اند
          شمرده می‌شوند ولی جلوی بقیه را نمی‌گیرند.
        </p>
        <textarea
          className="min-h-24 w-full rounded-md border bg-transparent p-2 text-sm"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          maxLength={1000}
          placeholder="متن پیام…"
        />
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        {result ? (
          <p className="text-sm text-muted-foreground">
            ارسال شد به {faNumber(result.sent)} نفر
            {result.failed ? ` — ${faNumber(result.failed)} نفر دریافت نکردند` : ''}
          </p>
        ) : null}
        <Button
          disabled={message.trim().length === 0 || busy || !customers?.total}
          onClick={() => void send()}
        >
          {busy ? 'در حال ارسال…' : 'ارسال به همه'}
        </Button>
      </div>
    </Card>
  )
}
