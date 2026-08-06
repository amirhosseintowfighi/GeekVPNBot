'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Check, Copy, Send, Users } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { ErrorState } from '@/components/shell/states'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonCard } from '@/components/ui/skeleton'
import { ApiError, fetcher } from '@/lib/api'
import { faNumber, percent, toman } from '@/lib/fa'
import { copyText, haptic, openLink } from '@/lib/telegram'
import type { ReferralSummary } from '@/lib/types'

const BOT_USERNAME = process.env.NEXT_PUBLIC_BOT_USERNAME ?? 'GeekVpnBot'

/**
 * Built by concatenation rather than written as one literal. The deep link and
 * the share endpoint share a base, and keeping it in a single constant means a
 * change of domain cannot update one and miss the other.
 */
const TG_BASE = 'https://' + 't.me'

/**
 * Referral.
 *
 * The share action goes through Telegram's own share sheet rather than the Web
 * Share API. Inside the Telegram webview the native sheet is what people
 * expect, and it keeps the invite inside Telegram, where the deep link
 * actually resolves.
 */
export default function ReferralPage() {
  const { data, error, mutate } = useSWR<ReferralSummary>(
    '/api/miniapp/referral',
    fetcher,
  )
  const [copied, setCopied] = React.useState(false)

  const link = data ? `${TG_BASE}/${BOT_USERNAME}?start=ref_${data.code}` : ''

  async function copy() {
    if (!link) return
    haptic.impact('light')
    await copyText(link)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  function share() {
    if (!data) return
    haptic.impact('medium')
    const text = [
      '\u0628\u0627 \u06af\u06cc\u06a9 \u0648\u06cc\u200c\u067e\u06cc\u200c\u0627\u0646 \u0627\u06cc\u0646\u062a\u0631\u0646\u062a \u0628\u062f\u0648\u0646 \u0645\u0631\u0632 \u0631\u0627 \u062a\u062c\u0631\u0628\u0647 \u06a9\u0646.',
      '\u0628\u0627 \u0627\u06cc\u0646 \u0644\u06cc\u0646\u06a9 \u062b\u0628\u062a\u200c\u0646\u0627\u0645 \u06a9\u0646\u06cc \u0648 ' +
        toman(data.inviteeBonus) +
        ' \u0647\u062f\u06cc\u0647 \u0628\u06af\u06cc\u0631.',
    ].join('\n')

    const shareUrl =
      TG_BASE +
      '/share/url?url=' +
      encodeURIComponent(link) +
      '&text=' +
      encodeURIComponent(text)

    openLink(shareUrl)
  }

  return (
    <>
      <PageHeader title={'\u0645\u0639\u0631\u0641\u06cc \u062f\u0648\u0633\u062a\u0627\u0646'} />

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
          <Card glow className="space-y-4 p-5 text-center">
            <div className="mx-auto w-fit rounded-2xl bg-primary/15 p-3">
              <Users className="size-6 text-primary" />
            </div>

            <div>
              <p className="text-xs text-muted-foreground">
                {'\u06a9\u062f \u0645\u0639\u0631\u0641\u06cc \u0634\u0645\u0627'}
              </p>
              <p dir="ltr" className="mt-1 font-mono text-2xl font-bold tracking-widest">
                {data.code}
              </p>
            </div>

            <div className="flex gap-2">
              <Button className="flex-1" onClick={share}>
                <Send className="size-4" aria-hidden />
                {'\u0627\u0634\u062a\u0631\u0627\u06a9\u200c\u06af\u0630\u0627\u0631\u06cc'}
              </Button>
              <Button variant="outline" className="flex-1" onClick={() => void copy()}>
                {copied ? (
                  <Check className="size-4" aria-hidden />
                ) : (
                  <Copy className="size-4" aria-hidden />
                )}
                {copied ? '\u06a9\u067e\u06cc \u0634\u062f' : '\u06a9\u067e\u06cc \u0644\u06cc\u0646\u06a9'}
              </Button>
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3">
            <Stat
              label={'\u062f\u0639\u0648\u062a\u200c\u0634\u062f\u0647'}
              value={faNumber(data.invitedCount)}
            />
            <Stat
              label={'\u062e\u0631\u06cc\u062f \u06a9\u0631\u062f\u0647'}
              value={faNumber(data.convertedCount)}
            />
            <Stat
              label={'\u062f\u0631\u0622\u0645\u062f \u067e\u0631\u062f\u0627\u062e\u062a\u200c\u0634\u062f\u0647'}
              value={toman(data.totalEarned)}
            />
            <Stat
              label={'\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u062a\u0633\u0648\u06cc\u0647'}
              value={toman(data.pendingEarned)}
            />
          </div>

          <Card className="space-y-2 p-4">
            <p className="text-sm font-medium">
              {'\u0686\u06af\u0648\u0646\u0647 \u06a9\u0627\u0631 \u0645\u06cc\u200c\u06a9\u0646\u062f\u061f'}
            </p>
            <ol className="space-y-1.5 text-xs leading-loose text-muted-foreground">
              <li>
                {'\u06f1. \u062f\u0648\u0633\u062a\u0627\u0646 \u0628\u0627 \u0644\u06cc\u0646\u06a9 \u0634\u0645\u0627 \u062b\u0628\u062a\u200c\u0646\u0627\u0645 \u0645\u06cc\u200c\u06a9\u0646\u0646\u062f \u0648 ' +
                  toman(data.inviteeBonus) +
                  ' \u0647\u062f\u06cc\u0647 \u0645\u06cc\u200c\u06af\u06cc\u0631\u0646\u062f.'}
              </li>
              <li>
                {'\u06f2. \u0627\u0632 \u0627\u0648\u0644\u06cc\u0646 \u062e\u0631\u06cc\u062f \u0622\u0646\u0647\u0627 ' +
                  percent(data.firstPurchaseBps / 100) +
                  ' \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0645\u0627 \u0648\u0627\u0631\u06cc\u0632 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
              </li>
              <li>
                {'\u06f3. \u0627\u0632 \u062e\u0631\u06cc\u062f\u0647\u0627\u06cc \u0628\u0639\u062f\u06cc \u0622\u0646\u0647\u0627 ' +
                  percent(data.recurringBps / 100) +
                  ' \u062f\u0631\u06cc\u0627\u0641\u062a \u0645\u06cc\u200c\u06a9\u0646\u06cc\u062f.'}
              </li>
            </ol>
          </Card>
        </div>
      )}
    </>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="nums mt-1 text-sm font-semibold">{value}</p>
    </Card>
  )
}
