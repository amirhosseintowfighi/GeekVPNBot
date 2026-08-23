'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Plus } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDate, faNumber } from '@/lib/fa'
import type { CampaignRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/**
 * Campaigns - including flash sales.
 *
 * A campaign is an automatic discount bound to a window, so unlike a coupon
 * nobody has to type anything: it simply applies. That makes an accidentally
 * live campaign expensive, which is why:
 *
 * - The window is always shown, and a campaign that is enabled but outside
 *   its window is labelled as scheduled or finished rather than active. An
 *   operator must never have to compare two dates in their head to know
 *   whether money is currently being discounted.
 * - Flash sales are marked, because their whole point is a short window and
 *   they are the ones most likely to be left running by mistake.
 * - Revenue and discount given sit side by side. A campaign that moved a lot
 *   of volume while giving away more than it earned is the failure mode this
 *   table exists to make visible.
 */
export default function CampaignsPage() {
  const { can } = useSession()
  const { data, error, isLoading, mutate } = useSWR<CampaignRow[]>('campaigns', () => api.campaigns())

  if (!can('packages.read')) return <ForbiddenState permission="packages.read" />

  const now = Date.now()

  return (
    <>
      <PageHeader
        title={'\u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627'}
        description={'\u062a\u062e\u0641\u06cc\u0641\u200c\u0647\u0627\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 \u0648 \u0641\u0631\u0648\u0634\u200c\u0647\u0627\u06cc \u0644\u062d\u0638\u0647\u200c\u0627\u06cc'}
        actions={
          can('campaigns.write') ? (
            <Button>
              <Plus className="size-3.5" aria-hidden />
              {'\u06a9\u0645\u067e\u06cc\u0646 \u062c\u062f\u06cc\u062f'}
            </Button>
          ) : null
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : ''}
          offline={error instanceof ApiError && error.status === 0}
          onRetry={() => mutate()}
        />
      ) : null}

      <Card>
        {isLoading && !data ? (
          <SkeletonTable rows={6} cols={7} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title={'\u06a9\u0645\u067e\u06cc\u0646\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647'}
            description={'\u06a9\u0645\u067e\u06cc\u0646 \u0628\u062f\u0648\u0646 \u0646\u06cc\u0627\u0632 \u0628\u0647 \u06a9\u062f\u060c \u062e\u0648\u062f\u06a9\u0627\u0631 \u0631\u0648\u06cc \u0642\u06cc\u0645\u062a \u0627\u0639\u0645\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u062f.'}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{'\u06a9\u0645\u067e\u06cc\u0646'}</TableHead>
                <TableHead>{'\u062a\u062e\u0641\u06cc\u0641'}</TableHead>
                <TableHead>{'\u0628\u0627\u0632\u0647'}</TableHead>
                <TableHead>{'\u0648\u0636\u0639\u06cc\u062a'}</TableHead>
                <TableHead>{'\u0633\u0641\u0627\u0631\u0634'}</TableHead>
                <TableHead>{'\u062a\u062e\u0641\u06cc\u0641 \u062f\u0627\u062f\u0647\u200c\u0634\u062f\u0647'}</TableHead>
                <TableHead>{'\u062f\u0631\u0622\u0645\u062f'}</TableHead>
                <TableHead>{'\u0641\u0639\u0627\u0644'}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((campaign) => {
                // The row carries a publication state and a formatted discount
                // label. It does not carry an `enabled` flag, a `discountBps`,
                // or per-campaign revenue - those live on
                // /catalog/campaigns/{id}/performance, which is a second call.
                const startsAt = campaign.startsAt ? new Date(campaign.startsAt).getTime() : null
                const endsAt = campaign.endsAt ? new Date(campaign.endsAt).getTime() : null

                // "Published" and "currently discounting" are different things.
                // The badge reports the second one.
                const published = campaign.state === 'published'
                const upcoming = startsAt !== null && startsAt > now
                const finished = endsAt !== null && endsAt < now
                const live = published && !upcoming && !finished

                const stateFa = live
                  ? '\u062f\u0631 \u062d\u0627\u0644 \u0627\u062c\u0631\u0627'
                  : upcoming
                    ? '\u0632\u0645\u0627\u0646\u200c\u0628\u0646\u062f\u06cc \u0634\u062f\u0647'
                    : finished
                      ? '\u067e\u0627\u06cc\u0627\u0646 \u06cc\u0627\u0641\u062a\u0647'
                      : '\u063a\u06cc\u0631\u0641\u0639\u0627\u0644'

                const tone = live ? 'success' : upcoming ? 'info' : finished ? 'muted' : 'outline'

                return (
                  <TableRow key={campaign.id}>
                    <TableCell>{campaign.nameFa}</TableCell>

                    <TableCell numeric>{campaign.discountLabel}</TableCell>

                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {(campaign.startsAt ? faDate(campaign.startsAt) : '\u2014') +
                        ' \u2014 ' +
                        (campaign.endsAt ? faDate(campaign.endsAt) : '\u0628\u062f\u0648\u0646 \u067e\u0627\u06cc\u0627\u0646')}
                    </TableCell>

                    <TableCell>
                      <Badge variant={tone} dot>
                        {stateFa}
                      </Badge>
                    </TableCell>

                    <TableCell numeric>{faNumber(campaign.redemptionCount)}</TableCell>
                    <TableCell numeric className="text-muted-foreground">
                      {campaign.remainingStock === null
                        ? '\u0646\u0627\u0645\u062d\u062f\u0648\u062f'
                        : faNumber(campaign.remainingStock)}
                    </TableCell>

                    <TableCell>
                      <Switch
                        checked={published}
                        disabled={!can('campaigns.write')}
                        onCheckedChange={async (checked) => {
                          await api.setCampaignState(campaign.id, checked ? 'published' : 'draft')
                          mutate()
                        }}
                      />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>
    </>
  )
}
