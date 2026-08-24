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
  CardBody,
  CardRow,
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
import type {
  CampaignCreateBody,
  CouponCreateBody,
  NodeCreateBody,
  NodeUpdateBody,
  PagedWithCursor,
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
  /** Field locations a 422 objected to, empty for every other status. */
  readonly fields: readonly string[]

  constructor(status: number, messageFa: string, fields: readonly string[] = []) {
    super(`admin api error ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.messageFa = messageFa
    this.fields = fields
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

/**
 * The fields a 422 objected to, named.
 *
 * "اطلاعات واردشده درست نیست" with no indication of which field leaves an
 * operator re-reading a form that looks correct - and it is not always a form
 * field at all: a missing `Idempotency-Key` header fails the same way and no
 * amount of staring at the inputs will reveal it. The API says exactly what it
 * rejected; there is no reason to withhold it.
 */
function fieldsFromErrors(body: unknown): string[] {
  if (typeof body !== 'object' || body === null) return []
  const errors = (body as { errors?: unknown }).errors
  if (!Array.isArray(errors)) return []
  return errors
    .map((error) => {
      const loc = (error as { loc?: unknown }).loc
      if (!Array.isArray(loc)) return null
      // Drop the leading "body"/"query" segment, which names the part of the
      // request rather than the field. "header" is kept: it is the difference
      // between a form the operator can fix and one they cannot.
      const parts = loc.map(String)
      const trimmed = parts[0] === 'body' || parts[0] === 'query' ? parts.slice(1) : parts
      return trimmed.join('.')
    })
    .filter((name): name is string => Boolean(name))
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
    let fields: string[] = []
    try {
      // `message_fa`, not `messageFa`. The API speaks problem details in
      // snake_case; reading the camelCase spelling meant `serverMessage` was
      // always undefined and every 401 fell through to "your session expired",
      // whatever had actually gone wrong.
      const body = (await response.json()) as { message_fa?: string }
      serverMessage = body.message_fa
      fields = fieldsFromErrors(body)
    } catch {
      // A non-JSON error body is a proxy or gateway page. Never render it.
    }
    const message = messageForStatus(response.status, serverMessage)
    throw new ApiError(
      response.status,
      fields.length > 0 ? `${message} (${fields.join('، ')})` : message,
      fields,
    )
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
  session: () => fetcher<AdminSession>(`${ROOT}/auth/me`),
  // The response body carries the token pair too, and it is deliberately
  // ignored: the session that matters is the httpOnly cookie the backend sets
  // alongside it, which every later request carries without JavaScript ever
  // touching a credential.
  signIn: (body: { username: string; password: string; totpCode?: string }) =>
    mutate<void>('POST', `${ROOT}/auth/login`, body),
  signOut: () => mutate<void>('POST', `${ROOT}/auth/sign-out`),

  // ----------------------------------------------------------- dashboard
  dashboard: (days: number) =>
    fetcher<DashboardSummary>(`${ROOT}/analytics/dashboard${qs({ days })}`),

  // --------------------------------------------------------------- users
  // limit/offset, because that is what the endpoint takes. It was being sent
  // page/page_size/tier/sort/direction, none of which it has ever accepted;
  // FastAPI ignores unknown query parameters, so every request quietly
  // returned the unfiltered, unsorted first page.
  users: (params: { page: number; pageSize?: number; query?: string; status?: string }) => {
    const limit = params.pageSize ?? 25
    return fetcher<Paged<UserRow>>(
      `${ROOT}/customers${qs({
        limit,
        offset: (params.page - 1) * limit,
        query: params.query,
        status: params.status,
      })}`,
    )
  },

  user: (userId: string) => fetcher<UserDetail>(`${ROOT}/customers/${userId}`),

  // Both return the customer alone, not the detail envelope.
  suspendUser: (userId: string, reason: string) =>
    mutate<UserRow>('POST', `${ROOT}/customers/${userId}/suspend`, { reason }),
  reinstateUser: (userId: string) =>
    mutate<UserRow>('POST', `${ROOT}/customers/${userId}/reinstate`),

  // -------------------------------------------------------- subscriptions
  subscriptions: (params: {
    page: number
    pageSize?: number
    state?: string
    userId?: number
    nodeId?: string
  }) => {
    const limit = params.pageSize ?? 25
    return fetcher<Paged<AdminSubscriptionRow>>(
      `${ROOT}/subscriptions${qs({
        limit,
        offset: (params.page - 1) * limit,
        state: params.state,
        user_id: params.userId,
        node_id: params.nodeId,
      })}`,
    )
  },

  // -------------------------------------------------------------- orders
  // state, number, limit, offset. The method/from/to filters it used to send
  // do not exist on the endpoint and were silently ignored.
  orders: (params: { page: number; pageSize?: number; state?: string; number?: string }) => {
    const limit = params.pageSize ?? 25
    return fetcher<Paged<OrderRow>>(
      `${ROOT}/orders${qs({
        limit,
        offset: (params.page - 1) * limit,
        state: params.state,
        number: params.number,
      })}`,
    )
  },

  order: (orderId: string) => fetcher<OrderDetail>(`${ROOT}/orders/${orderId}`),

  // The only action an order has. Approving, rejecting and refunding are
  // payment operations and live under /payments/{paymentId}; the three
  // methods that used to be here posted to /orders/{id}/approve|reject|refund,
  // which have never existed.
  retryProvision: (orderId: string) =>
    mutate<{ ok: boolean; subscriptionId: string | null; message: string | null }>(
      'POST',
      `${ROOT}/orders/${orderId}/retry-provision`,
    ),

  approvePayment: (paymentId: string, actualAmount?: number) =>
    mutate<Record<string, unknown>>('POST', `${ROOT}/payments/${paymentId}/approve`, {
      actualAmount: actualAmount ?? null,
    }),

  rejectPayment: (paymentId: string, reasonFa: string) =>
    mutate<Record<string, unknown>>('POST', `${ROOT}/payments/${paymentId}/reject`, { reasonFa }),

  refundPayment: (paymentId: string, amount: number, reasonFa: string) =>
    mutate<Record<string, unknown>>('POST', `${ROOT}/payments/${paymentId}/refund`, {
      amount,
      reasonFa,
    }),

  // ------------------------------------------------------------ catalog
  categories: () => fetcher<CategoryRow[]>(`${ROOT}/catalog/categories`),
  saveCategory: (body: Partial<CategoryRow>) =>
    mutate<CategoryRow>('POST', `${ROOT}/catalog/categories`, body),
  setCategoryState: (categoryId: string, state: string) =>
    mutate<CategoryRow>('PUT', `${ROOT}/catalog/categories/${categoryId}/state`, {
      publish: state === 'published',
    }),

  products: (params: { categoryId?: string; state?: string }) =>
    fetcher<ProductRow[]>(`${ROOT}/catalog/products${qs(params)}`),
  saveProduct: (body: Partial<ProductRow>) =>
    mutate<ProductRow>('POST', `${ROOT}/catalog/products`, body),
  // PUT with `{publish}`, which is what the route declares. This was POST with
  // `{state}` - wrong method and wrong body - so publishing anything from the
  // catalogue answered 405 and the operator was left with a draft they could
  // not put on sale.
  /**
   * Bind the product to the node that will provision it.
   *
   * `PUT /products/{id}/panel`, and the only reason a product can be
   * published: `Product.publish` refuses one that is not bound, and a package
   * cannot be published under an unpublished product. No screen called this,
   * so the chain stopped at its first link and the catalogue could never leave
   * draft.
   */
  bindProductPanel: (productId: string, nodeId: string, nodeTags: string[] = []) =>
    mutate<ProductRow>('PUT', `${ROOT}/catalog/products/${productId}/panel`, {
      nodeId,
      nodeTags,
    }),

  setProductState: (productId: string, state: string) =>
    mutate<ProductRow>('PUT', `${ROOT}/catalog/products/${productId}/state`, {
      publish: state === 'published',
    }),

  plans: (productId: string) => fetcher<PlanRow[]>(`${ROOT}/catalog/products/${productId}/plans`),
  savePlan: (body: Partial<PlanRow>) => mutate<PlanRow>('POST', `${ROOT}/catalog/plans`, body),
  setPlanState: (planId: string, state: string) =>
    mutate<PlanRow>('PUT', `${ROOT}/catalog/plans/${planId}/state`, {
      publish: state === 'published',
    }),

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
  }) => mutate<PlanRow[]>('POST', `${ROOT}/catalog/plans/generate-ladder`, body),

  // ------------------------------------------------------ panels/servers
  panels: () => fetcher<PanelRow[]>(`${ROOT}/panels`),
  savePanel: (body: NodeCreateBody) => mutate<PanelRow>('POST', `${ROOT}/panels`, body),
  // PATCH, and only the fields being changed. Posting a whole row back to
  // /panels created a second node instead of editing the one in front of you.
  updatePanel: (nodeId: string, patch: NodeUpdateBody) =>
    mutate<PanelRow>('PATCH', `${ROOT}/panels/${nodeId}`, patch),
  testPanel: (panelId: string) =>
    mutate<{ ok: boolean; latencyMs: number | null; version: string | null; message: string | null }>(
      'POST',
      `${ROOT}/panels/${panelId}/test-connection`,
    ),

  // A server *is* a node; there is one resource, not two.
  servers: () => fetcher<ServerRow[]>(`${ROOT}/panels`),
  saveServer: (nodeId: string, patch: NodeUpdateBody) =>
    mutate<ServerRow>('PATCH', `${ROOT}/panels/${nodeId}`, patch),

  // --------------------------------------------------------- promotions
  // A plain list, not a page: GET /catalog/coupons returns an array.
  coupons: (params: { state?: string }) =>
    fetcher<CouponRow[]>(`${ROOT}/catalog/coupons${qs(params)}`),
  saveCoupon: (body: CouponCreateBody) =>
    mutate<CouponRow>('POST', `${ROOT}/catalog/coupons`, body),
  bulkCreateCoupons: (body: { count: number; prefix: string; template: CouponCreateBody }) =>
    mutate<CouponRow[]>('POST', `${ROOT}/catalog/coupons/bulk`, body),
  // DELETE, which is what archives it. POST to the same path is not a route.
  archiveCoupon: (couponId: string) =>
    mutate<CouponRow>('DELETE', `${ROOT}/catalog/coupons/${couponId}`),

  campaigns: () => fetcher<CampaignRow[]>(`${ROOT}/catalog/campaigns`),
  saveCampaign: (body: CampaignCreateBody) =>
    mutate<CampaignRow>('POST', `${ROOT}/catalog/campaigns`, body),
  // The campaign route takes a verb - activate/pause/archive - not the
  // publication state the other three take. The screen was sending
  // "published"/"draft", which matches the pattern on neither side.
  setCampaignState: (campaignId: string, action: 'activate' | 'pause' | 'archive') =>
    mutate<CampaignRow>('PUT', `${ROOT}/catalog/campaigns/${campaignId}/state`, {
      state: action,
    }),

  // ------------------------------------------------------ destination cards
  // The card the customer is told to transfer to. Read from the database on
  // purpose - cards rotate constantly - and until now there was no way to put
  // one there but a hand-written INSERT.
  cards: () => fetcher<CardRow[]>(`${ROOT}/payments/cards`),
  createCard: (body: CardBody) => mutate<CardRow>('POST', `${ROOT}/payments/cards`, body),
  updateCard: (cardId: string, body: CardBody) =>
    mutate<CardRow>('PATCH', `${ROOT}/payments/cards/${cardId}`, body),

  // ---------------------------------------------------------- analytics
  // A window in days, matching GET /api/v1/admin/analytics, which takes
  // `days` (1..365) and nothing else. This was typed as a from/to/granularity
  // range that no endpoint has ever accepted, so the one screen calling it did
  // not compile and the panel could not be built at all.
  analytics: (days: number) => fetcher<AnalyticsBundle>(`${ROOT}/analytics${qs({ days })}`),

  // ---------------------------------------------------------- broadcast
  broadcasts: () => fetcher<BroadcastRow[]>(`${ROOT}/broadcasts`),
  estimateAudience: (audience: BroadcastAudience) =>
    mutate<{ count: number }>('POST', `${ROOT}/broadcasts/estimate`, audience),
  // Compose and send in one call, matching what the screen does: an operator
  // writes the message, sees the audience count, and sends. `sendNow: false`
  // leaves a draft that /broadcasts/{id}/send picks up later.
  sendBroadcast: (body: {
    segment: BroadcastAudience['segment']
    reference?: string | null
    titleFa: string
    bodyFa: string
    category: 'promos' | 'news' | 'critical'
    sendNow?: boolean
  }) => mutate<BroadcastRow>('POST', `${ROOT}/broadcasts`, body),
  cancelBroadcast: (broadcastId: string) =>
    mutate<BroadcastRow>('POST', `${ROOT}/broadcasts/${broadcastId}/cancel`),

  // ------------------------------------------------------------ tickets
  // category, priority, assigneeId and a page number. There is no free-text
  // query and no sort on this endpoint.
  tickets: (params: { page: number; category?: string; priority?: string; assigneeId?: number }) =>
    fetcher<PagedWithCursor<AdminTicketRow>>(`${ROOT}/tickets${qs(params)}`),
  ticket: (ticketId: string) => fetcher<AdminTicketRow>(`${ROOT}/tickets/${ticketId}`),
  // Wrapped in {items}, and a separate call from the ticket itself.
  ticketMessages: (ticketId: string) =>
    fetcher<{ items: AdminTicketMessage[] }>(`${ROOT}/tickets/${ticketId}/messages`),
  replyToTicket: (ticketId: string, message: string) =>
    mutate<AdminTicketMessage>('POST', `${ROOT}/tickets/${ticketId}/reply`, { message }),
  closeTicket: (ticketId: string) =>
    mutate<AdminTicketRow>('POST', `${ROOT}/tickets/${ticketId}/close`),

  // ------------------------------------------------------------- wallet
  // Per user, because that is the only wallet the API exposes: every route is
  // /wallet/{userId}/... There is no global ledger endpoint.
  walletStatement: (userId: string, params: { page: number; kind?: string }) =>
    fetcher<PagedWithCursor<WalletTransactionRow>>(
      `${ROOT}/wallets/${userId}/statement${qs(params)}`,
    ),

  // The user id is in the path and the body is {signedAmount, reasonFa} - not
  // a flat {userId, amount, descriptionFa} posted to /wallet/adjust, which is
  // not a route.
  walletBalance: (userId: string) =>
    fetcher<{ userId: number; balance: number }>(`${ROOT}/wallets/${userId}`),

  adjustWallet: (userId: string, signedAmount: number, reasonFa: string) =>
    mutate<{ entry: WalletTransactionRow; balance: number }>(
      'POST',
      `${ROOT}/wallets/${userId}/adjust`,
      { signedAmount, reasonFa },
    ),

  // --------------------------------------------------------------- logs
  // A plain list, and the only filters the endpoint has: actor, action, a
  // time window and limit/offset. level/entityType/query were invented.
  logs: (params: {
    page: number
    pageSize?: number
    actorId?: string
    action?: string
    since?: string
    until?: string
  }) => {
    const limit = params.pageSize ?? 50
    return fetcher<AuditLogRow[]>(
      `${ROOT}/audit-logs${qs({
        limit,
        offset: (params.page - 1) * limit,
        actor_id: params.actorId,
        action: params.action,
        since: params.since,
        until: params.until,
      })}`,
    )
  },

  // ----------------------------------------------------------- settings
  settings: () => fetcher<PolicySetting[]>(`${ROOT}/settings`),
  /**
   * One PUT per changed key, because that is the API there is.
   *
   * This used to send the whole draft to `PUT /settings`, a path that only
   * answers GET, so saving any setting failed with 405 and the screen reported
   * a generic error. The real route is `PUT /settings/{key}` with `{value}`.
   *
   * Sequential, not parallel: the failures worth having are the ones you can
   * read in order, and a settings screen saves a handful of keys, not a
   * hundred. A key that fails stops the run, leaving the earlier ones saved -
   * which the screen then shows, because it re-reads the server's list.
   */
  saveSettings: async (values: Record<string, number | boolean | string>) => {
    const updated: PolicySetting[] = []
    for (const [key, value] of Object.entries(values)) {
      updated.push(
        await mutate<PolicySetting>('PUT', `${ROOT}/settings/${encodeURIComponent(key)}`, {
          value,
        }),
      )
    }
    return updated
  },

  // -------------------------------------------------------- permissions
  operators: () => fetcher<OperatorRow[]>(`${ROOT}/admins`),
  // Username and password, which is how an operator signs in. There is no
  // display name or Telegram handle on this account.
  createOperator: (body: {
    username: string
    password: string
    role: Role
    email?: string | null
    telegramId?: number | null
  }) => mutate<OperatorRow>('POST', `${ROOT}/admins`, body),

  setOperatorRole: (operatorId: string, role: Role) =>
    mutate<OperatorRow>('PUT', `${ROOT}/admins/${operatorId}/role`, { role }),
  // The backend models disabling as deleting the operator, which also ends
  // every session they hold. There is no re-enable; create a new operator.
  disableOperator: (operatorId: string) =>
    mutate<OperatorRow>('DELETE', `${ROOT}/admins/${operatorId}`),
}
