/**
 * The only module in the admin panel that calls fetch.
 *
 * Centralising it decides four things once instead of at a hundred call
 * sites: authentication, error shaping, mutation semantics, and the fact
 * that a destructive call must carry an idempotency key.
 */

import type {
  AdminSession,
  AdminSubscriptionRow,
  AdminTicketMessage,
  AdminTicketRow,
  AnalyticsBundle,
  AuditLogRow,
  BroadcastAudience,
  BroadcastRow,
  CampaignRow,
  CategoryRow,
  CouponRow,
  DashboardSummary,
  DurationRung,
  OperatorRow,
  OrderDetail,
  OrderRow,
  Paged,
  PanelRow,
  PlanRow,
  PolicySetting,
  ProductRow,
  ServerRow,
  UserDetail,
  UserRow,
  WalletTransactionRow,
} from './types'
import type { Role } from './rbac'

export const BASE_URL = process.env.NEXT_PUBLIC_ADMIN_API_URL ?? ''

export const GENERIC_ERROR =
  '\u062e\u0637\u0627\u06cc\u06cc \u0631\u062e \u062f\u0627\u062f. \u062f\u0648\u0628\u0627\u0631\u0647 \u062a\u0644\u0627\u0634 \u06a9\u0646\u06cc\u062f.'

export const OFFLINE_ERROR =
  '\u0627\u062a\u0635\u0627\u0644 \u0628\u0631\u0642\u0631\u0627\u0631 \u0646\u0634\u062f. \u0627\u06cc\u0646\u062a\u0631\u0646\u062a \u0631\u0627 \u0628\u0631\u0631\u0633\u06cc \u06a9\u0646\u06cc\u062f.'

export const FORBIDDEN_ERROR =
  '\u0634\u0645\u0627 \u062f\u0633\u062a\u0631\u0633\u06cc \u0644\u0627\u0632\u0645 \u0628\u0631\u0627\u06cc \u0627\u06cc\u0646 \u0639\u0645\u0644\u06cc\u0627\u062a \u0631\u0627 \u0646\u062f\u0627\u0631\u06cc\u062f.'

export const SESSION_ERROR =
  '\u0646\u0634\u0633\u062a \u0634\u0645\u0627 \u0645\u0646\u0642\u0636\u06cc \u0634\u062f\u0647. \u062f\u0648\u0628\u0627\u0631\u0647 \u0648\u0627\u0631\u062f \u0634\u0648\u06cc\u062f.'

export class ApiError extends Error {
  readonly status: number
  readonly messageFa: string

  constructor(status: number, messageFa: string) {
    super(`admin api error ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.messageFa = messageFa
  }
}

/**
 * Session lives in an httpOnly cookie set by the backend, so there is no
 * token in JavaScript for a stray script or a browser extension to read.
 * That is why every request sends credentials and why there is no
 * Authorization header here.
 */
const BASE_INIT: RequestInit = {
  credentials: 'include',
  cache: 'no-store',
}

function messageForStatus(status: number, serverMessage?: string): string {
  if (serverMessage) return serverMessage
  if (status === 0) return OFFLINE_ERROR
  if (status === 401) return SESSION_ERROR
  if (status === 403) return FORBIDDEN_ERROR
  return GENERIC_ERROR
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response

  try {
    response = await fetch(BASE_URL + path, { ...BASE_INIT, ...init })
  } catch {
    // A thrown fetch is a network failure, not an HTTP status. Status 0 is
    // the sentinel the screens check to show an offline state instead of a
    // "something broke on our side" message that would send an operator
    // chasing a backend problem that does not exist.
    throw new ApiError(0, OFFLINE_ERROR)
  }

  if (!response.ok) {
    let serverMessage: string | undefined
    try {
      const body = (await response.json()) as { messageFa?: string }
      serverMessage = body.messageFa
    } catch {
      // A non-JSON error body is a proxy or gateway page. Never render it.
    }
    throw new ApiError(response.status, messageForStatus(response.status, serverMessage))
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** SWR fetcher. Read-only by construction. */
export function fetcher<T>(path: string): Promise<T> {
  return request<T>(path)
}

/**
 * Every mutation carries an idempotency key.
 *
 * An operator double-clicking "approve" on a card-to-card payment must not
 * provision two subscriptions, and a retried refund must not pay out twice.
 * The key is generated per call and the backend is expected to honour it.
 */
function mutate<T>(method: 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
}

/** Builds a query string, dropping empty values so URLs stay readable. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}

// The API mounts every admin route under the versioned prefix
// (`/api/v1/admin/...`). This constant was `/api/admin`, which no route
// ever answered, so every panel request 404'd.
const ROOT = '/api/v1/admin'

export const api = {
  // ------------------------------------------------------------- session
  session: () => fetcher<AdminSession>(`${ROOT}/session`),
  signOut: () => mutate<void>('POST', `${ROOT}/session/sign-out`),

  // ----------------------------------------------------------- dashboard
  dashboard: (days: number) =>
    fetcher<DashboardSummary>(`${ROOT}/dashboard${qs({ days })}`),

  // --------------------------------------------------------------- users
  users: (params: {
    page: number
    pageSize?: number
    query?: string
    state?: string
    tier?: string
  }) => fetcher<Paged<UserRow>>(`${ROOT}/users${qs({ page_size: 25, ...params })}`),

  user: (userId: string) => fetcher<UserDetail>(`${ROOT}/users/${userId}`),

  updateUser: (userId: string, patch: { displayName?: string; noteFa?: string }) =>
    mutate<UserDetail>('PATCH', `${ROOT}/users/${userId}`, patch),

  setUserState: (userId: string, state: 'active' | 'suspended' | 'banned', reasonFa: string) =>
    mutate<UserDetail>('POST', `${ROOT}/users/${userId}/state`, { state, reasonFa }),

  // -------------------------------------------------------- subscriptions
  subscriptions: (params: { page: number; query?: string; state?: string }) =>
    fetcher<Paged<AdminSubscriptionRow>>(`${ROOT}/subscriptions${qs(params)}`),

  rotateSubscription: (subscriptionId: string) =>
    mutate<AdminSubscriptionRow>('POST', `${ROOT}/subscriptions/${subscriptionId}/rotate`),

  // -------------------------------------------------------------- orders
  orders: (params: {
    page: number
    query?: string
    state?: string
    method?: string
    from?: string
    to?: string
  }) => fetcher<Paged<OrderRow>>(`${ROOT}/orders${qs(params)}`),

  order: (orderId: string) => fetcher<OrderDetail>(`${ROOT}/orders/${orderId}`),

  approveOrder: (orderId: string, noteFa?: string) =>
    mutate<OrderDetail>('POST', `${ROOT}/orders/${orderId}/approve`, { noteFa }),

  rejectOrder: (orderId: string, reasonFa: string) =>
    mutate<OrderDetail>('POST', `${ROOT}/orders/${orderId}/reject`, { reasonFa }),

  refundOrder: (orderId: string, amount: number, reasonFa: string) =>
    mutate<OrderDetail>('POST', `${ROOT}/orders/${orderId}/refund`, { amount, reasonFa }),

  // ------------------------------------------------------------ catalog
  categories: () => fetcher<CategoryRow[]>(`${ROOT}/categories`),
  saveCategory: (body: Partial<CategoryRow>) =>
    mutate<CategoryRow>('POST', `${ROOT}/categories`, body),

  products: (params: { categoryId?: string; state?: string }) =>
    fetcher<ProductRow[]>(`${ROOT}/products${qs(params)}`),
  saveProduct: (body: Partial<ProductRow>) =>
    mutate<ProductRow>('POST', `${ROOT}/products`, body),
  setProductState: (productId: string, state: string) =>
    mutate<ProductRow>('POST', `${ROOT}/products/${productId}/state`, { state }),

  plans: (productId: string) => fetcher<PlanRow[]>(`${ROOT}/products/${productId}/plans`),
  savePlan: (body: Partial<PlanRow>) => mutate<PlanRow>('POST', `${ROOT}/plans`, body),
  setPlanState: (planId: string, state: string) =>
    mutate<PlanRow>('POST', `${ROOT}/plans/${planId}/state`, { state }),

  /** The duration ladder from domain/catalog/durations.py. */
  durationLadder: () => fetcher<DurationRung[]>(`${ROOT}/duration-ladder`),

  /** Generates a whole ladder of plans from one monthly price. */
  generateLadder: (body: {
    productId: string
    monthlyPrice: number
    planType: string
    slugPrefix: string
    namePrefixFa: string
    monthlyQuotaGib?: number | null
    dailyQuotaGib?: number | null
    deviceLimit?: number
    cashbackBps?: number
    days?: number[]
  }) => mutate<PlanRow[]>('POST', `${ROOT}/plans/generate-ladder`, body),

  // ------------------------------------------------------ panels/servers
  panels: () => fetcher<PanelRow[]>(`${ROOT}/panels`),
  savePanel: (body: Partial<PanelRow> & { password?: string }) =>
    mutate<PanelRow>('POST', `${ROOT}/panels`, body),
  testPanel: (panelId: string) =>
    mutate<{ ok: boolean; messageFa: string; latencyMs: number | null }>(
      'POST',
      `${ROOT}/panels/${panelId}/test`,
    ),
  syncPanel: (panelId: string) =>
    mutate<PanelRow>('POST', `${ROOT}/panels/${panelId}/sync`),

  servers: () => fetcher<ServerRow[]>(`${ROOT}/servers`),
  saveServer: (body: Partial<ServerRow>) =>
    mutate<ServerRow>('POST', `${ROOT}/servers`, body),

  // --------------------------------------------------------- promotions
  coupons: (params: { page: number; query?: string; state?: string }) =>
    fetcher<Paged<CouponRow>>(`${ROOT}/coupons${qs(params)}`),
  saveCoupon: (body: Partial<CouponRow>) =>
    mutate<CouponRow>('POST', `${ROOT}/coupons`, body),
  bulkCreateCoupons: (body: { count: number; prefix: string; template: Partial<CouponRow> }) =>
    mutate<CouponRow[]>('POST', `${ROOT}/coupons/bulk`, body),
  archiveCoupon: (couponId: string) =>
    mutate<CouponRow>('POST', `${ROOT}/coupons/${couponId}/archive`),

  campaigns: () => fetcher<CampaignRow[]>(`${ROOT}/campaigns`),
  saveCampaign: (body: Partial<CampaignRow>) =>
    mutate<CampaignRow>('POST', `${ROOT}/campaigns`, body),
  setCampaignState: (campaignId: string, state: string) =>
    mutate<CampaignRow>('POST', `${ROOT}/campaigns/${campaignId}/state`, { state }),

  // ---------------------------------------------------------- analytics
  analytics: (params: { from: string; to: string; granularity: 'day' | 'week' | 'month' }) =>
    fetcher<AnalyticsBundle>(`${ROOT}/analytics${qs(params)}`),

  // ---------------------------------------------------------- broadcast
  broadcasts: () => fetcher<BroadcastRow[]>(`${ROOT}/broadcasts`),
  estimateAudience: (audience: BroadcastAudience) =>
    mutate<{ count: number }>('POST', `${ROOT}/broadcasts/estimate`, audience),
  saveBroadcast: (body: {
    titleFa: string
    bodyFa: string
    audience: BroadcastAudience
    scheduledAt: string | null
  }) => mutate<BroadcastRow>('POST', `${ROOT}/broadcasts`, body),
  sendBroadcast: (broadcastId: string) =>
    mutate<BroadcastRow>('POST', `${ROOT}/broadcasts/${broadcastId}/send`),
  cancelBroadcast: (broadcastId: string) =>
    mutate<BroadcastRow>('POST', `${ROOT}/broadcasts/${broadcastId}/cancel`),

  // ------------------------------------------------------------ tickets
  tickets: (params: { page: number; state?: string; query?: string }) =>
    fetcher<Paged<AdminTicketRow>>(`${ROOT}/tickets${qs(params)}`),
  ticketMessages: (ticketId: string) =>
    fetcher<AdminTicketMessage[]>(`${ROOT}/tickets/${ticketId}/messages`),
  replyToTicket: (ticketId: string, bodyFa: string) =>
    mutate<AdminTicketMessage>('POST', `${ROOT}/tickets/${ticketId}/messages`, { bodyFa }),
  setTicketState: (ticketId: string, state: string) =>
    mutate<AdminTicketRow>('POST', `${ROOT}/tickets/${ticketId}/state`, { state }),

  // ------------------------------------------------------------- wallet
  walletTransactions: (params: {
    page: number
    query?: string
    kind?: string
    from?: string
    to?: string
  }) => fetcher<Paged<WalletTransactionRow>>(`${ROOT}/wallet/transactions${qs(params)}`),

  adjustWallet: (body: { userId: string; amount: number; descriptionFa: string }) =>
    mutate<WalletTransactionRow>('POST', `${ROOT}/wallet/adjust`, body),

  // --------------------------------------------------------------- logs
  logs: (params: {
    page: number
    level?: string
    actor?: string
    entityType?: string
    query?: string
    from?: string
    to?: string
  }) => fetcher<Paged<AuditLogRow>>(`${ROOT}/logs${qs(params)}`),

  // ----------------------------------------------------------- settings
  settings: () => fetcher<PolicySetting[]>(`${ROOT}/settings`),
  saveSettings: (values: Record<string, number | boolean | string>) =>
    mutate<PolicySetting[]>('PUT', `${ROOT}/settings`, { values }),

  // -------------------------------------------------------- permissions
  operators: () => fetcher<OperatorRow[]>(`${ROOT}/operators`),
  saveOperator: (body: { operatorId?: string; telegramUsername: string; displayName: string; role: Role }) =>
    mutate<OperatorRow>('POST', `${ROOT}/operators`, body),
  setOperatorEnabled: (operatorId: string, isEnabled: boolean) =>
    mutate<OperatorRow>('POST', `${ROOT}/operators/${operatorId}/enabled`, { isEnabled }),
}
