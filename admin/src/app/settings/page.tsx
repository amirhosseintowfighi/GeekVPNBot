'use client'

import * as React from 'react'
import useSWR from 'swr'

import { api, ApiError } from '@/lib/api'
import { faNumber, normalizeInput, percent, toman } from '@/lib/fa'
import type { PolicySetting } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { CardsSection } from '@/components/feature/cards-section'
import { RequiredChannels } from '@/components/feature/required-channels'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SkeletonCards } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

/**
 * Namespaces, keyed on the first segment of the setting key.
 *
 * This used to be a hand-written list of five `pricing.*` prefixes, and every
 * row whose key started with anything else was filtered out and never drawn -
 * which was all eight of them, so the page rendered nothing at all. Grouping on
 * the namespace the key already has, with a catch-all underneath, means a new
 * setting appears the moment the backend declares it.
 */
const GROUP_TITLES: Record<string, string> = {
  wallet: 'کیف پول',
  pricing: 'قیمت‌گذاری',
  platform: 'پلتفرم',
  identity: 'ثبت‌نام و کاربران',
  security: 'امنیت',
  support: 'پشتیبانی',
}

const OTHER_TITLE = 'سایر'

function namespaceOf(key: string): string {
  return key.split('.')[0] ?? ''
}

function groupTitle(namespace: string): string {
  return GROUP_TITLES[namespace] ?? OTHER_TITLE
}

/**
 * Settings.
 *
 * These are the thirteen policy keys the pricing engine actually reads at
 * runtime, not a decorative preferences page. Changing `max_total_discount_bps`
 * changes what every customer pays tonight.
 *
 * Three consequences:
 * - Nothing saves on change. Edits are staged locally and committed with an
 *   explicit save, so a mis-typed digit in a percentage field does not reprice
 *   the catalogue mid-keystroke.
 * - Values are rendered in the unit an operator thinks in (percent, toman)
 *   while stored in the unit the engine uses (basis points, integer toman).
 * - Every value carries its Persian explanation inline. A key named
 *   `first_purchase_bps` means nothing at 2am during an incident.
 */
export default function SettingsPage() {
  const { can } = useSession()
  const [draft, setDraft] = React.useState<Record<string, string | number | boolean>>({})
  const [busy, setBusy] = React.useState(false)
  const [failure, setFailure] = React.useState<string | null>(null)
  const [saved, setSaved] = React.useState(false)

  const { data, error, isLoading, mutate } = useSWR<PolicySetting[]>('settings', () => api.settings())

  if (!can('settings.read')) return <ForbiddenState permission="settings.read" />

  const editable = can('settings.write')
  const dirty = Object.keys(draft).length > 0

  const valueOf = (setting: PolicySetting) =>
    draft[setting.key] !== undefined ? draft[setting.key] : setting.value

  const stage = (key: string, value: string | number | boolean) => {
    setSaved(false)
    setDraft((current) => ({ ...current, [key]: value }))
  }

  const save = async () => {
    setBusy(true)
    setFailure(null)
    try {
      await api.saveSettings(draft)
      setDraft({})
      setSaved(true)
      await mutate()
    } catch (thrown) {
      setFailure(thrown instanceof ApiError ? thrown.messageFa : '')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title={'\u062a\u0646\u0638\u06cc\u0645\u0627\u062a'}
        description={'\u0633\u06cc\u0627\u0633\u062a\u200c\u0647\u0627\u06cc \u0642\u06cc\u0645\u062a\u200c\u06af\u0630\u0627\u0631\u06cc\u060c \u06a9\u0634\u0628\u06a9 \u0648 \u0645\u0639\u0631\u0641\u06cc'}
        actions={
          editable ? (
            <Button loading={busy} disabled={!dirty} onClick={save}>
              {'\u0630\u062e\u06cc\u0631\u0647\u0654 \u062a\u063a\u06cc\u06cc\u0631\u0627\u062a'}
            </Button>
          ) : null
        }
      />

      {/* Cards first: without one the platform cannot take money at all, which
          outranks every pricing policy below it. */}
      <CardsSection />

      {/* Beside the other things that decide whether a customer can use the
          bot at all, rather than buried in the key/value list below - it is
          a gate, not a policy number. */}
      <RequiredChannels scope="platform" />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => mutate()}
        />
      ) : null}

      {saved ? (
        <p className="rounded-md border border-success/30 bg-success/10 px-3 py-2 text-2xs text-success">
          {'\u062a\u063a\u06cc\u06cc\u0631\u0627\u062a \u0630\u062e\u06cc\u0631\u0647 \u0634\u062f \u0648 \u0628\u0644\u0627\u0641\u0627\u0635\u0644\u0647 \u0627\u0639\u0645\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
        </p>
      ) : null}

      {failure ? (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-2xs text-destructive">
          {failure}
        </p>
      ) : null}

      {dirty ? (
        <p className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-2xs text-warning">
          {faNumber(Object.keys(draft).length) +
            ' \u062a\u063a\u06cc\u06cc\u0631 \u0630\u062e\u06cc\u0631\u0647\u200c\u0646\u0634\u062f\u0647 \u062f\u0627\u0631\u06cc\u062f.'}
        </p>
      ) : null}

      {isLoading && !data ? (
        <SkeletonCards count={4} />
      ) : (
        <div className="space-y-3">
          {Object.entries(
            (data ?? []).reduce<Record<string, PolicySetting[]>>((groups, setting) => {
              const title = groupTitle(namespaceOf(setting.key))
              groups[title] = [...(groups[title] ?? []), setting]
              return groups
            }, {}),
          ).map(([title, settings]) => (
            <Card key={title}>
              <CardHeader>
                <CardTitle>{title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {settings.map((setting) => {
                  const value = valueOf(setting)

                  return (
                    <div
                      key={setting.key}
                      className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3 last:border-0 last:pb-0"
                    >
                      <div className="min-w-48 flex-1">
                        <p className="text-2xs font-medium">{setting.labelFa}</p>
                        <p className="text-2xs text-muted-foreground">{setting.descriptionFa}</p>
                        {/* The raw key is shown deliberately: it is what
                            appears in the audit log and in the backend. */}
                        <code dir="ltr" className="mt-0.5 block text-2xs text-muted-foreground/60">
                          {setting.key}
                        </code>
                      </div>

                      <div className="flex items-center gap-2">
                        {setting.kind === 'boolean' ? (
                          <Switch
                            checked={Boolean(value)}
                            disabled={!editable}
                            onCheckedChange={(checked) => stage(setting.key, checked)}
                          />
                        ) : setting.kind === 'text' ? (
                          // Text, not digits. Every non-boolean used to go
                          // through a numeric filter, so typing in a message
                          // or a support handle reduced it to ۰.
                          <Input
                            disabled={!editable}
                            value={String(value)}
                            onChange={(event) => stage(setting.key, event.target.value)}
                            className="h-8 w-64 text-2xs"
                          />
                        ) : (
                          <>
                            <Input
                              ltr
                              inputMode="numeric"
                              disabled={!editable}
                              value={String(value)}
                              onChange={(event) =>
                                stage(
                                  setting.key,
                                  Number(
                                    normalizeInput(event.target.value).replace(/[^\d]/g, ''),
                                  ) || 0,
                                )
                              }
                              className="h-8 w-32 text-2xs"
                            />
                            {/* The human reading of the stored unit, so nobody
                                has to divide by 100 in their head. */}
                            <span className="nums min-w-20 text-2xs text-muted-foreground">
                              {setting.kind === 'bps'
                                ? percent(Number(value) / 100)
                                : setting.kind === 'toman'
                                  ? toman(Number(value))
                                  : ''}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
