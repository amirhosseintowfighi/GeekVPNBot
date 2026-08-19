'use client'

import * as React from 'react'
import useSWR from 'swr'
import { Check, Minus } from 'lucide-react'

import { api, ApiError } from '@/lib/api'
import { faDateTime } from '@/lib/fa'
import {
  ROLES,
  ROLE_LABEL_FA,
  can as roleCan,
  canAssignRole,
  permissionsFor,
  type Permission,
  type Role,
} from '@/lib/rbac'
import type { OperatorRow } from '@/lib/types'
import { useSession } from '@/components/shell/session'
import { PageHeader } from '@/components/shell/page-header'
import { ErrorState, ForbiddenState } from '@/components/shell/states'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SkeletonCards } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

/** Grouped by the resource each permission guards, in navigation order. */
const PERMISSION_GROUPS: Array<{ titleFa: string; permissions: Array<[Permission, string]> }> = [
  {
    titleFa: '\u0641\u0631\u0648\u0634 \u0648 \u0645\u0627\u0644\u06cc',
    permissions: [
      ['orders.view', '\u062f\u06cc\u062f\u0646 \u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627'],
      ['orders.approve', '\u062a\u0627\u06cc\u06cc\u062f \u067e\u0631\u062f\u0627\u062e\u062a'],
      ['orders.reject', '\u0631\u062f \u067e\u0631\u062f\u0627\u062e\u062a'],
      ['orders.refund', '\u0627\u0633\u062a\u0631\u062f\u0627\u062f \u0648\u062c\u0647'],
      ['wallet.view', '\u062f\u06cc\u062f\u0646 \u06a9\u06cc\u0641 \u067e\u0648\u0644'],
      ['wallet.adjust', '\u062a\u0639\u062f\u06cc\u0644 \u0645\u0648\u062c\u0648\u062f\u06cc'],
    ],
  },
  {
    titleFa: '\u06a9\u0627\u0631\u0628\u0631\u0627\u0646 \u0648 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc',
    permissions: [
      ['users.view', '\u062f\u06cc\u062f\u0646 \u06a9\u0627\u0631\u0628\u0631\u0627\u0646'],
      ['users.edit', '\u0648\u06cc\u0631\u0627\u06cc\u0634 \u06a9\u0627\u0631\u0628\u0631'],
      ['users.suspend', '\u062a\u0639\u0644\u06cc\u0642 \u06a9\u0627\u0631\u0628\u0631'],
      ['users.impersonate', '\u0648\u0631\u0648\u062f \u0628\u0647 \u062c\u0627\u06cc \u06a9\u0627\u0631\u0628\u0631'],
      ['tickets.view', '\u062f\u06cc\u062f\u0646 \u062a\u06cc\u06a9\u062a\u200c\u0647\u0627'],
      ['tickets.reply', '\u067e\u0627\u0633\u062e \u0628\u0647 \u062a\u06cc\u06a9\u062a'],
      ['tickets.close', '\u0628\u0633\u062a\u0646 \u062a\u06cc\u06a9\u062a'],
    ],
  },
  {
    titleFa: '\u0645\u062d\u0635\u0648\u0644 \u0648 \u0632\u06cc\u0631\u0633\u0627\u062e\u062a',
    permissions: [
      ['products.view', '\u062f\u06cc\u062f\u0646 \u0645\u062d\u0635\u0648\u0644\u0627\u062a'],
      ['products.edit', '\u0648\u06cc\u0631\u0627\u06cc\u0634 \u0645\u062d\u0635\u0648\u0644'],
      ['products.publish', '\u0627\u0646\u062a\u0634\u0627\u0631 \u0645\u062d\u0635\u0648\u0644'],
      ['panels.view', '\u062f\u06cc\u062f\u0646 \u067e\u0646\u0644\u200c\u0647\u0627'],
      ['panels.edit', '\u0648\u06cc\u0631\u0627\u06cc\u0634 \u067e\u0646\u0644'],
      ['panels.test', '\u062a\u0633\u062a \u0627\u062a\u0635\u0627\u0644 \u067e\u0646\u0644'],
      ['servers.view', '\u062f\u06cc\u062f\u0646 \u0633\u0631\u0648\u0631\u0647\u0627'],
      ['servers.edit', '\u0648\u06cc\u0631\u0627\u06cc\u0634 \u0633\u0631\u0648\u0631'],
    ],
  },
  {
    titleFa: '\u0628\u0627\u0632\u0627\u0631\u06cc\u0627\u0628\u06cc',
    permissions: [
      ['coupons.view', '\u062f\u06cc\u062f\u0646 \u06a9\u062f\u0647\u0627\u06cc \u062a\u062e\u0641\u06cc\u0641'],
      ['coupons.edit', '\u0633\u0627\u062e\u062a \u06a9\u062f \u062a\u062e\u0641\u06cc\u0641'],
      ['campaigns.view', '\u062f\u06cc\u062f\u0646 \u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627'],
      ['campaigns.edit', '\u0648\u06cc\u0631\u0627\u06cc\u0634 \u06a9\u0645\u067e\u06cc\u0646'],
      ['broadcast.view', '\u062f\u06cc\u062f\u0646 \u067e\u06cc\u0627\u0645 \u0647\u0645\u06af\u0627\u0646\u06cc'],
      ['broadcast.send', '\u0627\u0631\u0633\u0627\u0644 \u067e\u06cc\u0627\u0645 \u0647\u0645\u06af\u0627\u0646\u06cc'],
    ],
  },
  {
    titleFa: '\u0633\u0627\u0645\u0627\u0646\u0647',
    permissions: [
      ['dashboard.view', '\u062f\u0627\u0634\u0628\u0648\u0631\u062f'],
      ['analytics.view', '\u062a\u062d\u0644\u06cc\u0644\u200c\u0647\u0627'],
      ['analytics.export', '\u062e\u0631\u0648\u062c\u06cc \u062a\u062d\u0644\u06cc\u0644\u200c\u0647\u0627'],
      ['logs.view', '\u062f\u06cc\u062f\u0646 \u0644\u0627\u06af\u200c\u0647\u0627'],
      ['settings.view', '\u062f\u06cc\u062f\u0646 \u062a\u0646\u0638\u06cc\u0645\u0627\u062a'],
      ['settings.edit', '\u062a\u063a\u06cc\u06cc\u0631 \u062a\u0646\u0638\u06cc\u0645\u0627\u062a'],
      ['permissions.view', '\u062f\u06cc\u062f\u0646 \u062f\u0633\u062a\u0631\u0633\u06cc\u200c\u0647\u0627'],
      ['permissions.edit', '\u062a\u063a\u06cc\u06cc\u0631 \u062f\u0633\u062a\u0631\u0633\u06cc\u200c\u0647\u0627'],
    ],
  },
]

/**
 * Permissions.
 *
 * Two tabs, because "what can a role do" and "who has which role" are
 * different questions asked at different times.
 *
 * The matrix is read-only on purpose. Roles are defined in `rbac.ts` and
 * enforced again on the server; letting an operator invent a bespoke role from
 * the browser would produce a permission set the backend has never heard of.
 * What this screen gives instead is honesty: the full grid, so nobody has to
 * guess why support cannot issue a refund.
 *
 * Assignment is guarded by `canAssignRole`, which forbids granting a role at
 * or above your own rank, and forbids granting `owner` to anyone, ever. That
 * single rule is what stops an admin from quietly promoting themselves.
 */
export default function PermissionsPage() {
  const { can, role } = useSession()

  const { data, error, isLoading, mutate } = useSWR<OperatorRow[]>('operators', () => api.operators())

  if (!can('permissions.view')) return <ForbiddenState permission="permissions.view" />

  const editable = can('permissions.edit')

  return (
    <>
      <PageHeader
        title={'\u062f\u0633\u062a\u0631\u0633\u06cc\u200c\u0647\u0627'}
        description={'\u0646\u0642\u0634\u200c\u0647\u0627\u06cc \u062a\u0639\u0631\u06cc\u0641\u200c\u0634\u062f\u0647 \u0648 \u0627\u067e\u0631\u0627\u062a\u0648\u0631\u0647\u0627\u06cc \u0633\u0627\u0645\u0627\u0646\u0647'}
      />

      <Tabs defaultValue="operators">
        <TabsList>
          <TabsTrigger value="operators">{'\u0627\u067e\u0631\u0627\u062a\u0648\u0631\u0647\u0627'}</TabsTrigger>
          <TabsTrigger value="matrix">{'\u0645\u0627\u062a\u0631\u06cc\u0633 \u0646\u0642\u0634\u200c\u0647\u0627'}</TabsTrigger>
        </TabsList>

        <TabsContent value="operators">
          {error ? (
            <ErrorState
              messageFa={error instanceof ApiError ? error.messageFa : ''}
              offline={error instanceof ApiError && error.status === 0}
              onRetry={() => mutate()}
            />
          ) : isLoading && !data ? (
            <SkeletonCards count={2} />
          ) : (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{'\u0627\u067e\u0631\u0627\u062a\u0648\u0631'}</TableHead>
                    <TableHead>{'\u0646\u0642\u0634'}</TableHead>
                    <TableHead>{'\u0622\u062e\u0631\u06cc\u0646 \u0648\u0631\u0648\u062f'}</TableHead>
                    <TableHead>{'\u0641\u0639\u0627\u0644'}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data ?? []).map((operator) => {
                    // You may only touch an operator whose role you are
                    // allowed to assign - i.e. strictly below your own rank.
                    const mayManage =
                      editable && role !== null && canAssignRole(role, operator.role)

                    return (
                      <TableRow key={operator.id}>
                        <TableCell>
                          <p dir="ltr" className="font-mono">{operator.username}</p>
                          <p className="text-2xs text-muted-foreground">
                            {operator.isTotpEnabled ? 'دوعاملی فعال' : 'بدون دوعاملی'}
                          </p>
                        </TableCell>
                        <TableCell>
                          {mayManage ? (
                            <Select
                              value={operator.role}
                              onValueChange={async (next) => {
                                await api.setOperatorRole(operator.id, next as Role)
                                mutate()
                              }}
                            >
                              <SelectTrigger className="h-8 w-32 text-2xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {ROLES.filter(
                                  (candidate) => role !== null && canAssignRole(role, candidate),
                                ).map((candidate) => (
                                  <SelectItem key={candidate} value={candidate}>
                                    {ROLE_LABEL_FA[candidate]}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          ) : (
                            <Badge variant={operator.role === 'owner' ? 'default' : 'muted'}>
                              {ROLE_LABEL_FA[operator.role]}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {operator.lastLoginAt
                            ? faDateTime(operator.lastLoginAt)
                            : '\u0647\u0631\u06af\u0632'}
                        </TableCell>
                        <TableCell>
                          <Switch
                            checked
                            // Disabling is one-way server-side: it deletes the
                            // operator and ends their sessions, so a listed
                            // operator is by definition still enabled.
                            disabled={!mayManage}
                            onCheckedChange={async () => {
                              await api.disableOperator(operator.id)
                              mutate()
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </Card>
          )}

          <p className="mt-2 text-2xs text-muted-foreground">
            {'\u0646\u0642\u0634 \u0645\u0627\u0644\u06a9 \u0642\u0627\u0628\u0644 \u0648\u0627\u06af\u0630\u0627\u0631\u06cc \u0646\u06cc\u0633\u062a \u0648 \u0647\u06cc\u0686 \u0627\u067e\u0631\u0627\u062a\u0648\u0631\u06cc \u0646\u0645\u06cc\u200c\u062a\u0648\u0627\u0646\u062f \u0646\u0642\u0634\u06cc \u0647\u0645\u200c\u0633\u0637\u062d \u06cc\u0627 \u0628\u0627\u0644\u0627\u062a\u0631 \u0627\u0632 \u062e\u0648\u062f \u0631\u0627 \u0628\u0647 \u062f\u06cc\u06af\u0631\u06cc \u0628\u062f\u0647\u062f.'}
          </p>
        </TabsContent>

        <TabsContent value="matrix">
          <div className="space-y-3">
            {PERMISSION_GROUPS.map((group) => (
              <Card key={group.titleFa}>
                <CardHeader>
                  <CardTitle>{group.titleFa}</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="sticky-col">{'\u062f\u0633\u062a\u0631\u0633\u06cc'}</TableHead>
                          {ROLES.map((candidate) => (
                            <TableHead key={candidate} className="text-center">
                              {ROLE_LABEL_FA[candidate]}
                            </TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {group.permissions.map(([permission, labelFa]) => (
                          <TableRow key={permission}>
                            <TableCell className="sticky-col">
                              <p>{labelFa}</p>
                              <code dir="ltr" className="text-2xs text-muted-foreground/60">
                                {permission}
                              </code>
                            </TableCell>
                            {ROLES.map((candidate) => {
                              const allowed = roleCan(candidate, permission)
                              return (
                                <TableCell key={candidate} className="text-center">
                                  {allowed ? (
                                    <Check className="mx-auto size-3.5 text-success" aria-label={'\u0645\u062c\u0627\u0632'} />
                                  ) : (
                                    <Minus
                                      className="mx-auto size-3.5 text-muted-foreground/40"
                                      aria-label={'\u063a\u06cc\u0631\u0645\u062c\u0627\u0632'}
                                    />
                                  )}
                                </TableCell>
                              )
                            })}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            ))}

            <p className="text-2xs text-muted-foreground">
              {'\u0645\u062c\u0645\u0648\u0639 \u062f\u0633\u062a\u0631\u0633\u06cc \u0645\u0627\u0644\u06a9: \u0647\u0645\u0647\u0654 \u0645\u0648\u0627\u0631\u062f \u0628\u062f\u0648\u0646 \u0627\u0633\u062a\u062b\u0646\u0627 (' +
                permissionsFor('owner').length +
                ').'}
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </>
  )
}
