'use client'

import Link from 'next/link'
import useSWR from 'swr'
import {
  ChevronLeft,
  Clock,
  Gift,
  HeadphonesIcon,
  Server,
  ShoppingBag,
  User,
  Wallet as WalletIcon,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Logo } from '@/components/brand/logo'
import { SkeletonCard } from '@/components/ui/skeleton'
import { EmptyState, ErrorState, StaggerItem, StaggerList } from '@/components/shell/states'
import { SubscriptionCardView } from '@/components/feature/subscription-card'
import { api, ApiError, fetcher } from '@/lib/api'
import { toman } from '@/lib/fa'
import type { PendingPayment, SubscriptionCard, WalletSnapshot } from '@/lib/types'

const TIER_LABEL: Record<string, string> = {
  bronze: '\u0628\u0631\u0646\u0632\u06cc',
  silver: '\u0646\u0642\u0631\u0647\u200c\u0627\u06cc',
  gold: '\u0637\u0644\u0627\u06cc\u06cc',
  diamond: '\u0627\u0644\u0645\u0627\u0633\u06cc',
}

const TIER_EMOJI: Record<string, string> = {
  bronze: '\ud83e\udd49',
  silver: '\ud83e\udd48',
  gold: '\ud83e\udd47',
  diamond: '\ud83d\udc8e',
}

/**
 * Home.
 *
 * Ordering here is not decorative. A customer opening the app almost always
 * wants one of three things, in this order: check whether a pending payment
 * cleared, check how much traffic is left, or buy. Anything promotional sits
 * below all three.
 */
export default function HomePage() {
  const wallet = useSWR<WalletSnapshot>('/api/miniapp/wallet', fetcher)
  const subs = useSWR<SubscriptionCard[]>('/api/miniapp/subscriptions', fetcher)
  const pending = useSWR<PendingPayment[]>(
    '/api/miniapp/payments/pending',
    fetcher,
  )

  const loading = !wallet.data && !wallet.error
  const activeSubs = (subs.data ?? []).filter(
    (sub) => sub.state !== 'expired' && sub.state !== 'pending',
  )

  if (wallet.error instanceof ApiError && !wallet.data) {
    return (
      <ErrorState
        messageFa={wallet.error.messageFa}
        offline={wallet.error.status === 0}
        onRetry={() => void wallet.mutate()}
      />
    )
  }

  return (
    <div className="space-y-6 pb-4">
      {/* Brand bar. The home tab has no PageHeader, so the logo stands in for
          the title, as it does on the desktop and Android clients. */}
      <header className="flex items-center gap-3 pt-2">
        <Logo className="size-10 text-white" />
        <p className="min-w-0 flex-1">
          <span className="font-display text-xl font-bold leading-none" dir="ltr">
            GeekVPN
          </span>
        </p>
        <Link
          href="/profile"
          aria-label={'\u067e\u0631\u0648\u0641\u0627\u06cc\u0644'}
          className="glass-clear flex size-11 items-center justify-center rounded-[15px] active:scale-95"
        >
          <User className="size-5" aria-hidden />
        </Link>
      </header>

      {/* Wallet + tier: the navy panel, the one dark block on the screen. */}
      {loading ? (
        <SkeletonCard />
      ) : (
        <section className="navy-panel space-y-5 rounded-3xl p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[13px] text-muted-foreground">
                {'\u0645\u0648\u062c\u0648\u062f\u06cc \u06a9\u06cc\u0641 \u067e\u0648\u0644'}
              </p>
              <p className="nums mt-1.5 text-[28px] font-extrabold leading-none">
                {toman(wallet.data?.balance ?? 0)}
              </p>
            </div>
            <Badge variant="outline" className="shrink-0 gap-1">
              <span aria-hidden>{TIER_EMOJI[wallet.data?.tier ?? 'bronze']}</span>
              {TIER_LABEL[wallet.data?.tier ?? 'bronze']}
            </Badge>
          </div>

          <div className="flex gap-2">
            <Button variant="accent" asChild className="flex-1">
              <Link href="/wallet/topup">
                <WalletIcon aria-hidden />
                {'\u0627\u0641\u0632\u0627\u06cc\u0634 \u0645\u0648\u062c\u0648\u062f\u06cc'}
              </Link>
            </Button>
            <Button variant="secondary" asChild className="flex-1">
              <Link href="/shop">
                <ShoppingBag aria-hidden />
                {'\u062e\u0631\u06cc\u062f \u0628\u0633\u062a\u0647'}
              </Link>
            </Button>
          </div>
        </section>
      )}

      {/* Pending payments. Placed above services because "did my transfer go
          through?" is the question that otherwise becomes a support ticket. */}
      {(pending.data ?? []).length > 0 ? (
        <section className="space-y-2">
          <h2 className="section-label">
            {'\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0628\u0631\u0631\u0633\u06cc'}
          </h2>
          {pending.data!.map((payment) => (
            <Link key={payment.paymentId} href={`/payments/${payment.paymentId}`}>
              <Card className="flex items-center justify-between gap-3 p-3.5 active:scale-[0.99]">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="icon-tile bg-warning-soft text-warning-ink">
                    <Clock className="size-5" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <p className="nums truncate text-sm font-bold">
                      {toman(payment.amount)}
                    </p>
                    <p className="nums truncate text-xs text-muted-foreground">
                      {`\u06a9\u062f \u067e\u06cc\u06af\u06cc\u0631\u06cc ${payment.reference}`}
                    </p>
                  </div>
                </div>
                <ChevronLeft className="size-5 shrink-0 text-muted-foreground" aria-hidden />
              </Card>
            </Link>
          ))}
        </section>
      ) : null}

      {/* Active services */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="section-label">
            {'\u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644'}
          </h2>
          {activeSubs.length > 0 ? (
            <Link
              href="/services"
              className="px-1 py-2 text-[13px] font-bold text-white underline-offset-4 hover:underline"
            >
              {'\u0645\u0634\u0627\u0647\u062f\u0647 \u0647\u0645\u0647'}
            </Link>
          ) : null}
        </div>

        {!subs.data && !subs.error ? (
          <SkeletonCard />
        ) : activeSubs.length === 0 ? (
          <EmptyState
            icon={ShoppingBag}
            title={'\u0647\u0646\u0648\u0632 \u0633\u0631\u0648\u06cc\u0633 \u0641\u0639\u0627\u0644\u06cc \u0646\u062f\u0627\u0631\u06cc\u062f'}
            description={'\u06cc\u06a9 \u0628\u0633\u062a\u0647 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646\u06cc\u062f \u062a\u0627 \u062f\u0631 \u06a9\u0645\u062a\u0631 \u0627\u0632 \u06cc\u06a9 \u062f\u0642\u06cc\u0642\u0647 \u0641\u0639\u0627\u0644 \u0634\u0648\u062f.'}
            action={
              <Button asChild size="sm">
                <Link href="/shop">
                  {'\u062f\u06cc\u062f\u0646 \u0628\u0633\u062a\u0647\u200c\u0647\u0627'}
                </Link>
              </Button>
            }
          />
        ) : (
          <StaggerList className="space-y-3">
            {activeSubs.slice(0, 2).map((sub) => (
              <StaggerItem key={sub.subscriptionId}>
                <SubscriptionCardView sub={sub} />
              </StaggerItem>
            ))}
          </StaggerList>
        )}
      </section>

      {/* Secondary destinations. These mirror the bot's menu so someone who
          learned the bot first is not hunting for them. */}
      <section className="grid grid-cols-3 gap-2">
        <QuickLink href="/referral" icon={Gift} label={'\u0645\u0639\u0631\u0641\u06cc \u062f\u0648\u0633\u062a\u0627\u0646'} />
        <QuickLink href="/support" icon={HeadphonesIcon} label={'\u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc'} />
        <QuickLink href="/status" icon={Server} label={'\u0648\u0636\u0639\u06cc\u062a \u0633\u0631\u0648\u0631\u0647\u0627'} />
      </section>
    </div>
  )
}

function QuickLink({
  href,
  icon: Icon,
  label,
}: {
  href: string
  icon: React.ComponentType<{ className?: string }>
  label: string
}) {
  return (
    <Link href={href} className="rounded-3xl active:scale-[0.98]">
      <Card className="flex h-full flex-col items-center justify-center gap-2.5 rounded-[22px] px-2 py-4 text-center">
        <span className="icon-tile">
          <Icon className="size-5" />
        </span>
        <span className="text-xs font-bold leading-tight">
          {label}
        </span>
      </Card>
    </Link>
  )
}
