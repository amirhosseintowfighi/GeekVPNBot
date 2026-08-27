'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Handshake, Plus } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faNumber, percent, toman } from '@/lib/fa'
import type { PanelRow, ResellerRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { EmptyState, ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SkeletonTable } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { NewResellerDialog } from '@/components/feature/new-reseller-dialog'
import { ResellerDrawer } from '@/components/feature/reseller-drawer'

const STATUS_LABEL: Record<ResellerRow['status'], string> = {
  active: 'فعال',
  suspended: 'معلق',
  closed: 'بسته',
}

/**
 * Resellers.
 *
 * The list leads with the balance, because that is the number that decides
 * whether a reseller's customers have a working service this minute: a
 * negative balance suspends all of them until it is positive again, and that
 * suspension is the credit limit this platform enforces.
 *
 * Everything else about a reseller - their discount, their per-package prices,
 * which panels they may sell from, their credit history - lives in the drawer
 * rather than on this table. A reseller is configured rarely and looked at
 * often, and a table wide enough to edit in is a table nobody can scan.
 */
export default function ResellersPage() {
  const { can } = useSession()
  const [creating, setCreating] = React.useState(false)
  const [openId, setOpenId] = React.useState<string | null>(null)

  const { data, error, isLoading, mutate } = useSWR<ResellerRow[]>('resellers', () =>
    api.resellers(),
  )
  // Panels are needed to render the "which panels may they sell from" picker
  // and are the same list for every reseller, so they load once here.
  const { data: panels } = useSWR<PanelRow[]>('panels', () => api.panels())

  if (!can('resellers.read')) return <ForbiddenState permission="resellers.read" />

  const open = data?.find((row) => row.id === openId) ?? null

  return (
    <div className="space-y-6">
      <PageHeader
        title="نمایندگان"
        description="کسانی که با نام خودشان می‌فروشند: قیمت اختصاصی، اعتبار، و پنل‌هایی که اجازه دارند"
        actions={
          can('resellers.write') ? (
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" />
              نماینده جدید
            </Button>
          ) : null
        }
      />

      {error ? (
        <ErrorState
          messageFa={error instanceof ApiError ? error.messageFa : 'فهرست نمایندگان بارگذاری نشد.'}
          onRetry={() => void mutate()}
        />
      ) : isLoading ? (
        <SkeletonTable rows={4} />
      ) : !data?.length ? (
        <EmptyState
          icon={Handshake}
          title="هنوز نماینده‌ای ندارید"
          description="یک نماینده بسازید تا با قیمت اختصاصی خودش بفروشد."
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>نام</TableHead>
                <TableHead>وضعیت</TableHead>
                <TableHead>موجودی</TableHead>
                <TableHead>تخفیف</TableHead>
                <TableHead>پنل‌ها</TableHead>
                <TableHead>ربات</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer"
                  onClick={() => setOpenId(row.id)}
                >
                  <TableCell className="font-medium">
                    {row.nameFa}
                    {row.contactFa ? (
                      <div className="text-xs text-muted-foreground">{row.contactFa}</div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    {/* Arrears outranks the status label: a reseller can be
                        "active" and still have every one of their customers
                        switched off, and that is the thing to say first. */}
                    {row.inArrears ? (
                      <Badge variant="destructive">بدهکار</Badge>
                    ) : (
                      <Badge variant={row.status === 'active' ? 'success' : 'muted'}>
                        {STATUS_LABEL[row.status]}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className={row.balance < 0 ? 'text-destructive' : undefined}>
                    {toman(row.balance)}
                  </TableCell>
                  <TableCell>{percent(row.discountPercent)}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {row.allowedNodeIds.length
                      ? faNumber(row.allowedNodeIds.length)
                      : 'همه'}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {row.hasBot ? (row.botUsername ?? 'تنظیم شده') : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      {creating ? (
        <NewResellerDialog
          onClose={() => setCreating(false)}
          onCreated={() => void mutate()}
        />
      ) : null}

      {open ? (
        <ResellerDrawer
          reseller={open}
          panels={panels ?? []}
          onClose={() => setOpenId(null)}
          onChanged={() => void mutate()}
        />
      ) : null}
    </div>
  )
}
