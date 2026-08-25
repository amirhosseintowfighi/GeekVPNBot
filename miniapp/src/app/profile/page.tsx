'use client'

import * as React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import {
  ChevronLeft,
  HelpCircle,
  Pencil,
  Server,
  Settings as SettingsIcon,
  Users,
} from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { ErrorState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { SkeletonCard } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { api, ApiError, fetcher } from '@/lib/api'
import { faDate, faNumber, normalizeInput, toman } from '@/lib/fa'
import { haptic } from '@/lib/telegram'
import type { LoyaltyTier, ProfileSummary } from '@/lib/types'

const MIN_NAME = 2
const MAX_NAME = 50

/** Thresholds and labels mirror the bot's loyalty tables exactly. */
const TIERS: Array<{
  key: LoyaltyTier
  labelFa: string
  emoji: string
  threshold: number
}> = [
  { key: 'bronze', labelFa: '\u0628\u0631\u0646\u0632\u06cc', emoji: '\ud83e\udd49', threshold: 0 },
  { key: 'silver', labelFa: '\u0646\u0642\u0631\u0647\u200c\u0627\u06cc', emoji: '\ud83e\udd48', threshold: 1_000_000 },
  { key: 'gold', labelFa: '\u0637\u0644\u0627\u06cc\u06cc', emoji: '\ud83e\udd47', threshold: 3_000_000 },
  { key: 'diamond', labelFa: '\u0627\u0644\u0645\u0627\u0633\u06cc', emoji: '\ud83d\udc8e', threshold: 10_000_000 },
]

function tierIndex(tier: LoyaltyTier): number {
  return Math.max(0, TIERS.findIndex((t) => t.key === tier))
}

export default function ProfilePage() {
  const { data, error, mutate } = useSWR<ProfileSummary>(
    '/api/miniapp/profile',
    fetcher,
  )

  const [editing, setEditing] = React.useState(false)
  const [name, setName] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)

  const trimmed = normalizeInput(name).trim()
  const nameValid = trimmed.length >= MIN_NAME && trimmed.length <= MAX_NAME

  function openEditor() {
    setName(data?.displayName ?? '')
    setFormError(null)
    setEditing(true)
  }

  async function saveName() {
    if (!nameValid) return
    setBusy(true)
    setFormError(null)
    try {
      const updated = await api.updateProfile({ displayName: trimmed })
      await mutate(updated, { revalidate: false })
      haptic.notify('success')
      setEditing(false)
    } catch (err) {
      haptic.notify('error')
      setFormError(
        err instanceof ApiError
          ? err.messageFa
          : '\u0630\u062e\u06cc\u0631\u0647 \u0646\u0627\u0645 \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
      )
    } finally {
      setBusy(false)
    }
  }

  const current = data ? TIERS[tierIndex(data.tier)]! : null
  const next = data ? TIERS[tierIndex(data.tier) + 1] : undefined

  // Progress is measured across the current band, not from zero, otherwise a
  // gold customer sits at a near-full bar for a very long time and the bar
  // stops telling them anything.
  const bandProgress =
    data && next && current
      ? Math.min(
          1,
          Math.max(
            0,
            (data.lifetimeSpend - current.threshold) /
              (next.threshold - current.threshold),
          ),
        )
      : 1

  return (
    <>
      <PageHeader title={'\u067e\u0631\u0648\u0641\u0627\u06cc\u0644'} back={false} />

      {error instanceof ApiError && !data ? (
        <ErrorState
          messageFa={error.messageFa}
          offline={error.status === 0}
          onRetry={() => void mutate()}
        />
      ) : !data ? (
        <SkeletonCard />
      ) : (
        <div className="space-y-4 pb-4">
          <Card className="space-y-4 p-5">
            <div className="flex items-center gap-3">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-full bg-brand-gradient text-lg font-bold text-primary-foreground">
                {(data.displayName ?? '\u06a9').slice(0, 1)}
              </div>

              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">
                  {data.displayName ||
                    '\u06a9\u0627\u0631\u0628\u0631 \u06af\u06cc\u06a9 \u0648\u06cc\u200c\u067e\u06cc\u200c\u0627\u0646'}
                </p>
                {data.username ? (
                  <p dir="ltr" className="truncate text-start text-xs text-muted-foreground">
                    {'@' + data.username}
                  </p>
                ) : null}
              </div>

              <Button variant="ghost" size="icon" onClick={openEditor} aria-label={'\u0648\u06cc\u0631\u0627\u06cc\u0634 \u0646\u0627\u0645'}>
                <Pencil className="size-4" aria-hidden />
              </Button>
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Badge variant="outline" className="gap-1">
                  <span aria-hidden>{current!.emoji}</span>
                  {'\u0633\u0637\u062d ' + current!.labelFa}
                </Badge>
                {next ? (
                  <span className="nums text-[11px] text-muted-foreground">
                    {'\u062a\u0627 ' +
                      next.labelFa +
                      ': ' +
                      toman(Math.max(0, next.threshold - data.lifetimeSpend))}
                  </span>
                ) : (
                  <span className="text-[11px] text-muted-foreground">
                    {'\u0628\u0627\u0644\u0627\u062a\u0631\u06cc\u0646 \u0633\u0637\u062d'}
                  </span>
                )}
              </div>
              <Progress value={bandProgress * 100} />
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-secondary/40 px-3 py-2">
                <p className="text-muted-foreground">
                  {'\u062a\u0639\u062f\u0627\u062f \u0633\u0641\u0627\u0631\u0634'}
                </p>
                <p className="nums mt-0.5 font-medium">{faNumber(data.orderCount)}</p>
              </div>
              <div className="rounded-lg bg-secondary/40 px-3 py-2">
                <p className="text-muted-foreground">
                  {'\u0639\u0636\u0648\u06cc\u062a \u0627\u0632'}
                </p>
                <p className="nums mt-0.5 font-medium">{faDate(data.joinedAt)}</p>
              </div>
            </div>
          </Card>

          {/* The rest of the bot's menu lives here. */}
          <Card className="divide-y divide-border/70 p-0">
            <MenuRow href="/settings" icon={SettingsIcon} label={'\u062a\u0646\u0638\u06cc\u0645\u0627\u062a'} />
            <MenuRow href="/referral" icon={Users} label={'\u0645\u0639\u0631\u0641\u06cc \u062f\u0648\u0633\u062a\u0627\u0646'} />
            <MenuRow href="/faq" icon={HelpCircle} label={'\u0633\u0648\u0627\u0644\u0627\u062a \u0645\u062a\u062f\u0627\u0648\u0644'} />
            <MenuRow href="/status" icon={Server} label={'\u0648\u0636\u0639\u06cc\u062a \u0633\u0631\u0648\u0631\u0647\u0627'} />
          </Card>
        </div>
      )}

      <Sheet open={editing} onOpenChange={setEditing}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>
              {'\u0648\u06cc\u0631\u0627\u06cc\u0634 \u0646\u0627\u0645 \u0646\u0645\u0627\u06cc\u0634\u06cc'}
            </SheetTitle>
          </SheetHeader>

          <div className="space-y-3">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={MAX_NAME}
              placeholder={'\u0646\u0627\u0645 \u0634\u0645\u0627'}
            />
            <p className="nums text-[11px] text-muted-foreground">
              {'\u0628\u06cc\u0646 ' +
                faNumber(MIN_NAME) +
                ' \u062a\u0627 ' +
                faNumber(MAX_NAME) +
                ' \u062d\u0631\u0641'}
            </p>

            {formError ? (
              <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-loose text-destructive">
                {formError}
              </p>
            ) : null}

            <Button full loading={busy} disabled={!nameValid} onClick={() => void saveName()}>
              {'\u0630\u062e\u06cc\u0631\u0647'}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}

function MenuRow({
  href,
  icon: Icon,
  label,
}: {
  href: string
  icon: React.ComponentType<{ className?: string }>
  label: string
}) {
  return (
    <Link
      href={href}
      onClick={haptic.select}
      className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-secondary/40"
    >
      <Icon className="size-4 shrink-0 text-primary" aria-hidden />
      <span className="flex-1 text-sm">{label}</span>
      {/* Points to the end of the line, which is the left edge in RTL. */}
      <ChevronLeft className="size-4 shrink-0 text-muted-foreground" aria-hidden />
    </Link>
  )
}
