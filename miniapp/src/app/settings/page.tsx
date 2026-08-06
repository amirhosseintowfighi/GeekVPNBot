'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Moon } from 'lucide-react'

import { PageHeader } from '@/components/shell/page-header'
import { ErrorState } from '@/components/shell/states'
import { Card } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { SkeletonCard } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api, ApiError, fetcher } from '@/lib/api'
import { haptic } from '@/lib/telegram'
import type { NotificationPreferences } from '@/lib/types'

/**
 * Keys, labels and descriptions match the bot's `Notifier.Category` set.
 *
 * Critical alerts are deliberately absent: they bypass both the per-category
 * switches and quiet hours in the notifier, so offering a toggle here would
 * be a control that does nothing.
 */
const TOGGLES: Array<{
  key: keyof Omit<NotificationPreferences, 'quietHours'>
  labelFa: string
  descriptionFa: string
}> = [
  {
    key: 'expiry',
    labelFa: '\u06cc\u0627\u062f\u0622\u0648\u0631\u06cc \u0627\u0646\u0642\u0636\u0627',
    descriptionFa:
      '\u067e\u06cc\u0634 \u0627\u0632 \u067e\u0627\u06cc\u0627\u0646 \u0627\u0639\u062a\u0628\u0627\u0631 \u0633\u0631\u0648\u06cc\u0633 \u062e\u0628\u0631 \u0645\u06cc\u200c\u062f\u0647\u06cc\u0645.',
  },
  {
    key: 'traffic',
    labelFa: '\u0647\u0634\u062f\u0627\u0631 \u062d\u062c\u0645',
    descriptionFa:
      '\u0648\u0642\u062a\u06cc \u062d\u062c\u0645 \u0628\u0627\u0642\u06cc\u200c\u0645\u0627\u0646\u062f\u0647 \u06a9\u0645 \u0634\u0648\u062f \u0627\u0637\u0644\u0627\u0639 \u0645\u06cc\u200c\u062f\u0647\u06cc\u0645.',
  },
  {
    key: 'promos',
    labelFa: '\u062a\u062e\u0641\u06cc\u0641\u200c\u0647\u0627 \u0648 \u067e\u06cc\u0634\u0646\u0647\u0627\u062f\u0647\u0627',
    descriptionFa:
      '\u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627 \u0648 \u0641\u0631\u0648\u0634\u200c\u0647\u0627\u06cc \u0648\u06cc\u0698\u0647.',
  },
  {
    key: 'news',
    labelFa: '\u0627\u062e\u0628\u0627\u0631 \u0633\u0631\u0648\u06cc\u0633',
    descriptionFa:
      '\u062a\u063a\u06cc\u06cc\u0631\u0627\u062a \u0645\u0647\u0645 \u0648 \u0627\u0645\u06a9\u0627\u0646\u0627\u062a \u062c\u062f\u06cc\u062f.',
  },
]

export default function SettingsPage() {
  const { data, error, mutate } = useSWR<NotificationPreferences>(
    '/api/miniapp/preferences',
    fetcher,
  )
  const [saveError, setSaveError] = React.useState<string | null>(null)

  /**
   * Toggles are optimistic. A switch that waits for a round trip before it
   * moves feels broken on a slow mobile connection, and the failure path here
   * is cheap: roll the value back and say so.
   */
  async function toggle(key: keyof NotificationPreferences, value: boolean) {
    if (!data) return
    haptic.select()
    const next = { ...data, [key]: value }
    setSaveError(null)

    await mutate(
      async () => {
        try {
          return await api.savePreferences(next)
        } catch (err) {
          setSaveError(
            err instanceof ApiError
              ? err.messageFa
              : '\u0630\u062e\u06cc\u0631\u0647\u200c\u06cc \u062a\u0646\u0638\u06cc\u0645\u0627\u062a \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f.',
          )
          haptic.notify('error')
          return data
        }
      },
      { optimisticData: next, rollbackOnError: true, revalidate: false },
    )
  }

  return (
    <>
      <PageHeader title={'\u062a\u0646\u0638\u06cc\u0645\u0627\u062a'} />

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
          <Card className="p-0">
            <div className="px-4 pt-4">
              <p className="text-sm font-medium">
                {'\u0627\u0637\u0644\u0627\u0639\u200c\u0631\u0633\u0627\u0646\u06cc'}
              </p>
            </div>

            <ul className="mt-2 divide-y divide-border/70">
              {TOGGLES.map((item) => (
                <li
                  key={item.key}
                  className="flex items-start justify-between gap-4 px-4 py-3.5"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">{item.labelFa}</p>
                    <p className="mt-0.5 text-[11px] leading-loose text-muted-foreground">
                      {item.descriptionFa}
                    </p>
                  </div>
                  <Switch
                    checked={data[item.key]}
                    onCheckedChange={(value) => void toggle(item.key, value)}
                    aria-label={item.labelFa}
                    className="mt-1 shrink-0"
                  />
                </li>
              ))}
            </ul>

            <Separator />

            <div className="flex items-start justify-between gap-4 px-4 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 text-sm">
                  <Moon className="size-3.5 text-primary" aria-hidden />
                  {'\u0633\u0627\u0639\u0627\u062a \u0633\u06a9\u0648\u062a'}
                </p>
                <p className="mt-0.5 text-[11px] leading-loose text-muted-foreground">
                  {'\u0628\u06cc\u0646 \u06f2\u06f3 \u062a\u0627 \u06f8 \u0628\u0627\u0645\u062f\u0627\u062f \u067e\u06cc\u0627\u0645\u06cc \u0627\u0631\u0633\u0627\u0644 \u0646\u0645\u06cc\u200c\u0634\u0648\u062f. \u0647\u0634\u062f\u0627\u0631\u0647\u0627\u06cc \u0628\u062d\u0631\u0627\u0646\u06cc \u0627\u0633\u062a\u062b\u0646\u0627 \u0647\u0633\u062a\u0646\u062f.'}
                </p>
              </div>
              <Switch
                checked={data.quietHours}
                onCheckedChange={(value) => void toggle('quietHours', value)}
                aria-label={'\u0633\u0627\u0639\u0627\u062a \u0633\u06a9\u0648\u062a'}
                className="mt-1 shrink-0"
              />
            </div>
          </Card>

          {saveError ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs leading-loose text-destructive">
              {saveError}
            </p>
          ) : null}

          <p className="px-1 text-[11px] leading-loose text-muted-foreground">
            {'\u0627\u06cc\u0646 \u062a\u0646\u0638\u06cc\u0645\u0627\u062a \u0628\u0627 \u0631\u0628\u0627\u062a \u06cc\u06a9\u0633\u0627\u0646 \u0627\u0633\u062a\u061b \u062a\u063a\u06cc\u06cc\u0631 \u062f\u0631 \u0647\u0631 \u06a9\u062f\u0627\u0645\u060c \u062f\u0631 \u062f\u06cc\u06af\u0631\u06cc \u0647\u0645 \u0627\u0639\u0645\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
          </p>
        </div>
      )}
    </>
  )
}
